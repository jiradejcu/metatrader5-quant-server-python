import json
import logging
import math
import os
import threading
import time

from app.utils.redis_client import get_redis_connection
from app.connectors.binance.api.order import get_open_orders, cancel_all_open_orders, chase_order, close_order
from app.connectors.binance.api.position import get_position
from app.connectors.binance.api.ticker import get_ticker
from app.connectors.binance.api.depth import get_order_book
from ..arbitrage import config
from ..trading_sessions import is_within_trading_session, minutes_until_next_session

logger = logging.getLogger(__name__)

latest_prediction_settings = None

QTY_PRECISION = int(os.getenv('PREDICTION_QTY_PRECISION', '3'))

# "passive" chases a post-only best-ask SELL (same order style grid_bot uses
# to enter) — zero slippage, but only fills if the market comes to it.
# "aggressive" crosses the book with a reduce-only IOC SELL bounded by
# max_slippage_usd — guarantees getting flat (or as close as the book
# allows) at the cost of paying the spread/slippage. Meant for e.g. forcing
# the position closed before the trading session reopens and grid_bot
# resumes.
AGGRESSIVENESS_PASSIVE = "passive"
AGGRESSIVENESS_AGGRESSIVE = "aggressive"


def _parse_prediction_settings(settings_dict):
    aggressiveness = str(settings_dict.get('aggressiveness', AGGRESSIVENESS_PASSIVE)).strip().lower()
    if aggressiveness not in (AGGRESSIVENESS_PASSIVE, AGGRESSIVENESS_AGGRESSIVE):
        aggressiveness = AGGRESSIVENESS_PASSIVE

    return {
        "profit_target_usd": float(settings_dict.get('profit_target_usd', 0.0)),
        "max_slippage_usd": float(settings_dict.get('max_slippage_usd', 0.0)),
        "aggressiveness": aggressiveness,
        "reentry_tolerance_usd": float(settings_dict.get('reentry_tolerance_usd', 0.0)),
        # Caps how much of the position a single close order can target, so a
        # large position gets closed in clips instead of one order. <= 0
        # means uncapped — close the full position at once.
        "max_close_size": float(settings_dict.get('max_close_size', 0.0)),
        # Once this many minutes (or fewer) remain before the trading
        # session reopens, force aggressive closing regardless of the
        # configured aggressiveness — so the position is flat before
        # grid_bot resumes instead of left waiting on a passive fill.
        # <= 0 disables the auto-escalation.
        "force_aggressive_minutes_before_reopen": float(
            settings_dict.get('force_aggressive_minutes_before_reopen', 0.0)
        ),
    }


def _capped_close_qty(position_amt, max_close_size):
    if max_close_size and max_close_size > 0:
        return min(position_amt, max_close_size)
    return position_amt


def _resolve_effective_settings(primary_symbol, hedge_symbol, settings):
    """Auto-escalate aggressiveness to "aggressive" when few minutes remain
    before the trading session reopens, so the bot forces itself flat before
    grid_bot resumes rather than leaving a passive order that may never fill
    in time. A no-op when already aggressive, or when the escalation window
    is disabled (force_aggressive_minutes_before_reopen <= 0).
    """
    if settings['aggressiveness'] == AGGRESSIVENESS_AGGRESSIVE:
        return settings

    threshold = settings['force_aggressive_minutes_before_reopen']
    if threshold <= 0:
        return settings

    minutes_left = minutes_until_next_session(primary_symbol, hedge_symbol)
    if minutes_left is None or minutes_left > threshold:
        logger.debug(
            f"[Prediction] Escalation check: minutes_left={minutes_left} threshold={threshold} — not escalating"
        )
        return settings

    logger.info(
        f"[Prediction] {minutes_left:.1f}m until session reopens (<= {threshold}) — forcing aggressive close"
    )
    return dict(settings, aggressiveness=AGGRESSIVENESS_AGGRESSIVE)


def _max_closeable_qty(bids, remaining_qty, max_slippage_usd):
    """Walk the bid book and return (qty, worst_price) closeable without the
    cumulative cost of crossing the book exceeding max_slippage_usd.

    Slippage at a level is (best_price - level_price) * quantity_filled_there.
    Returns (0.0, None) when even the best price can't be used (empty book or
    nothing left to close).
    """
    if not bids or remaining_qty <= 0:
        return 0.0, None

    best_price = bids[0][0]
    filled = 0.0
    slippage_cost = 0.0
    worst_price = best_price

    for price, qty in bids:
        level_qty = min(qty, remaining_qty - filled)
        if level_qty <= 0:
            break

        level_slippage = (best_price - price) * level_qty
        if slippage_cost + level_slippage > max_slippage_usd:
            remaining_budget = max_slippage_usd - slippage_cost
            allowed_qty = level_qty if price >= best_price else remaining_budget / (best_price - price)
            allowed_qty = max(0.0, min(allowed_qty, level_qty))
            if allowed_qty > 0:
                filled += allowed_qty
                worst_price = price
            break

        filled += level_qty
        slippage_cost += level_slippage
        worst_price = price

        if filled >= remaining_qty:
            break

    return filled, worst_price


def _round_down(value, decimals=QTY_PRECISION):
    factor = 10 ** decimals
    return math.floor(value * factor) / factor


def get_enable_status():
    return get_redis_connection().get("prediction_bot_enabled_flag")


_COMPUTED_ACTIVE_FLAG = "prediction_bot_computed_active_flag"
# Set inline on every loop iteration (poll_interval cadence), doubling as a
# liveness heartbeat: if the tick loop dies, the flag expires and status
# correctly reads inactive instead of staying stuck.
_COMPUTED_ACTIVE_TTL = 5


def _set_computed_active(is_active):
    redis_conn = get_redis_connection()
    if is_active:
        redis_conn.set(_COMPUTED_ACTIVE_FLAG, "1", ex=_COMPUTED_ACTIVE_TTL)
    else:
        redis_conn.delete(_COMPUTED_ACTIVE_FLAG)


# Remembers the entry price/size of the position last seen open, so that once
# it's closed we know what "back to entry" means for reacquiring it. qty here
# is always the *original* size the position had when this holding cycle
# began — not whatever's left after any max_close_size clips — so a
# reacquire always targets the full original size.
_last_position = {"entry_price": None, "qty": None}

# Size of the position the first time it was observed since it last went
# flat. Reset to None on every flat tick, then set once on the next non-zero
# tick; stays fixed afterward so partial closes don't shrink it.
_original_position_qty = {"value": None}


def _reset_position_tracking():
    """Anchor tracking to the start of a new non-trading window: whatever
    grid_bot left the position at when the session just closed becomes the
    fresh reference point, instead of carrying over stale state from an
    earlier window the position may never have gone flat within.
    """
    _original_position_qty['value'] = None
    _last_position['entry_price'] = None
    _last_position['qty'] = None


def _close_passive(primary_symbol, position_amt, open_orders, max_close_size):
    """Chase a post-only best-ask SELL, same order style as grid_bot's entries."""
    if not open_orders:
        qty = _capped_close_qty(position_amt, max_close_size)
        logger.info(
            f"[Prediction] Placing passive best-ask SELL for {qty}/{position_amt} on {primary_symbol}"
        )
        chase_order(primary_symbol, qty, 'SELL', order_id=None)
        return

    order = open_orders[0]
    side = getattr(order, 'side', None)
    if side != 'SELL':
        logger.warning(f"[Prediction] Unexpected {side} order while closing (passive) — cancelling")
        cancel_all_open_orders(primary_symbol)
        return

    order_id = getattr(order, 'order_id', None)
    qty = float(getattr(order, 'orig_qty', position_amt))
    logger.debug(f"[Prediction] Chasing close order_id={order_id} qty={qty}")
    chase_order(primary_symbol, qty, 'SELL', order_id=order_id)


def _close_aggressive(primary_symbol, position_amt, open_orders, max_slippage_usd, max_close_size):
    """Cross the book with a reduce-only IOC SELL bounded by max_slippage_usd."""
    if open_orders:
        # A resting passive order can only get here if aggressiveness was just
        # switched mid-flight — pull it so the two styles don't stack.
        logger.info("[Prediction] Switching to aggressive close — cancelling resting order first")
        cancel_all_open_orders(primary_symbol)
        return

    target_qty = _capped_close_qty(position_amt, max_close_size)
    order_book = get_order_book(primary_symbol)
    bids = (order_book or {}).get('bids', [])
    close_qty, worst_price = _max_closeable_qty(bids, target_qty, max_slippage_usd)
    close_qty = _round_down(close_qty)

    if close_qty <= 0 or worst_price is None:
        logger.debug(
            f"[Prediction] Aggressive close: book too thin to close within slippage budget "
            f"({max_slippage_usd}) — waiting"
        )
        return

    logger.info(
        f"[Prediction] Aggressive close {close_qty}/{target_qty}/{position_amt} {primary_symbol} "
        f"at worst_price={worst_price} (slippage_budget={max_slippage_usd})"
    )
    close_order(primary_symbol, close_qty, 'SELL', worst_price)


def _handle_holding_or_closing(primary_symbol, position_amt, position, open_orders, settings):
    entry_price = float((position or {}).get('entryPrice', 0) or 0)
    ticker = get_ticker(primary_symbol)
    if not ticker or not entry_price:
        logger.debug(
            f"[Prediction] Holding/closing check skipped on {primary_symbol}: "
            f"ticker={'ok' if ticker else 'missing'} entry_price={entry_price}"
        )
        return

    profit_usd = float(ticker['best_bid']) - entry_price
    target_met = profit_usd >= settings['profit_target_usd']

    if not target_met:
        if open_orders:
            logger.info(
                f"[Prediction] Profit target no longer met (profit={profit_usd:.2f}) — cancelling close order"
            )
            cancel_all_open_orders(primary_symbol)
        else:
            logger.debug(
                f"[Prediction] Holding {position_amt} {primary_symbol}: "
                f"profit={profit_usd:.2f} < target={settings['profit_target_usd']:.2f}"
            )
        return

    if settings['aggressiveness'] == AGGRESSIVENESS_AGGRESSIVE:
        _close_aggressive(
            primary_symbol, position_amt, open_orders,
            settings['max_slippage_usd'], settings['max_close_size'],
        )
    else:
        _close_passive(primary_symbol, position_amt, open_orders, settings['max_close_size'])


def _handle_reacquire(primary_symbol, open_orders, settings, qty):
    """Buy back whatever portion of the last-tracked position is still
    missing (qty) once price falls to within reentry_tolerance_usd of the
    price it was originally entered at — i.e. the run-up got given back, so
    re-enter at (roughly) the same basis. Runs regardless of whether the
    position is fully flat or only partially closed; `qty` is the gap
    between the original size and whatever's currently held.

    Uses the same passive chase-at-best-price style as grid_bot's entries.
    Disabled (falls through to plain stray-order cleanup) when there's no
    remembered position yet, nothing missing, or reentry_tolerance_usd is 0.
    """
    entry_price = _last_position['entry_price']
    tolerance = settings['reentry_tolerance_usd']

    if not entry_price or not qty or qty <= 0 or tolerance <= 0:
        if open_orders:
            logger.info("[Prediction] No position but open order(s) found — cancelling")
            cancel_all_open_orders(primary_symbol)
        else:
            logger.debug(
                f"[Prediction] Reacquire skipped on {primary_symbol}: "
                f"entry_price={entry_price} qty={qty} tolerance={tolerance}"
            )
        return

    ticker = get_ticker(primary_symbol)
    if not ticker:
        return

    ask = float(ticker['best_ask'])
    back_at_entry = ask <= entry_price + tolerance

    if not back_at_entry:
        if open_orders:
            logger.info(
                f"[Prediction] Price {ask:.2f} back above reentry band "
                f"(entry={entry_price:.2f} + tolerance={tolerance:.2f}) — cancelling"
            )
            cancel_all_open_orders(primary_symbol)
        else:
            logger.debug(
                f"[Prediction] Flat on {primary_symbol}, waiting for price to fall back to "
                f"entry={entry_price:.2f} (+tolerance {tolerance:.2f}); ask={ask:.2f}"
            )
        return

    if not open_orders:
        logger.info(
            f"[Prediction] Price {ask:.2f} back near entry={entry_price:.2f} — "
            f"reacquiring {qty} on {primary_symbol}"
        )
        chase_order(primary_symbol, qty, 'BUY', order_id=None)
        return

    order = open_orders[0]
    side = getattr(order, 'side', None)
    if side != 'BUY':
        logger.warning(f"[Prediction] Unexpected {side} order while reacquiring — cancelling")
        cancel_all_open_orders(primary_symbol)
        return

    order_id = getattr(order, 'order_id', None)
    order_qty = float(getattr(order, 'orig_qty', qty))
    logger.debug(f"[Prediction] Chasing reacquire order_id={order_id} qty={order_qty}")
    chase_order(primary_symbol, order_qty, 'BUY', order_id=order_id)


def _process_tick(primary_symbol, settings):
    """Execute one prediction-bot decision. This bot never opens a *new*
    position — the grid bot is responsible for entries. It watches an
    existing long and closes it once the profit target is met (passive or
    aggressive per settings['aggressiveness']), and — independently, on the
    same tick — will buy back any portion of the original size that's
    currently missing (whether fully flat or only partially closed) once
    price falls back to within reentry_tolerance_usd of where it was
    originally entered. Under normal settings (profit_target_usd >
    reentry_tolerance_usd) the two zones don't overlap, so at most one side
    ever has a resting order at a time.
    """
    position = get_position(primary_symbol)
    position_amt = float((position or {}).get('positionAmt', 0) or 0)
    logger.debug(f"[Prediction] Tick: {primary_symbol} position_amt={position_amt} settings={settings}")

    if position_amt < 0:
        logger.warning(
            f"[Prediction] Unexpected short position {position_amt} on {primary_symbol} — "
            "this algorithm only manages longs, skipping tick"
        )
        return

    open_orders = get_open_orders(primary_symbol)
    close_orders = [o for o in open_orders if getattr(o, 'side', None) == 'SELL']
    reacquire_orders = [o for o in open_orders if getattr(o, 'side', None) == 'BUY']

    if position_amt > 0:
        entry_price = float((position or {}).get('entryPrice', 0) or 0)
        if entry_price > 0:
            if _original_position_qty['value'] is None:
                _original_position_qty['value'] = position_amt
            _last_position['entry_price'] = entry_price
            _last_position['qty'] = _original_position_qty['value']
        _handle_holding_or_closing(primary_symbol, position_amt, position, close_orders, settings)
    else:
        _original_position_qty['value'] = None

    missing_qty = _round_down((_last_position['qty'] or 0) - position_amt)
    _handle_reacquire(primary_symbol, reacquire_orders, settings, missing_qty)


def handle_prediction_flow(pubsub, settings_channel, primary_symbol, hedge_symbol, poll_interval=2.0):
    global latest_prediction_settings
    latest_prediction_settings = None
    was_in_trading_session = True

    try:
        redis_conn = get_redis_connection()
        initial = redis_conn.get(settings_channel)
        if initial:
            latest_prediction_settings = _parse_prediction_settings(json.loads(initial))
            logger.debug(f"[Prediction] Initial settings loaded: {latest_prediction_settings}")
    except Exception as e:
        logger.error(f"[Prediction] Failed to fetch initial settings: {e}")

    def _pubsub_worker():
        global latest_prediction_settings
        while True:
            try:
                for message in pubsub.listen():
                    if message['type'] != 'message':
                        continue
                    channel = message['channel'].decode('utf-8')
                    if channel == settings_channel:
                        data_payload = message['data']
                        latest_prediction_settings = _parse_prediction_settings(
                            json.loads(data_payload) if data_payload else {}
                        )
                        logger.info(f"[Prediction] Settings updated: {latest_prediction_settings}")
            except Exception as e:
                logger.error(f"[Prediction] Critical PubSub failure: {e}. Reconnecting in 1s...", exc_info=True)
                time.sleep(1)

    threading.Thread(target=_pubsub_worker, daemon=True).start()

    while True:
        try:
            in_trading_session = is_within_trading_session(primary_symbol, hedge_symbol)

            # The moment the session closes is the starting point for this
            # window's position tracking (see _reset_position_tracking) —
            # whatever grid_bot left the position at becomes the fresh
            # reference, regardless of what the prior window was tracking.
            if was_in_trading_session and not in_trading_session:
                logger.info("[Prediction] Trading session ended — anchoring position tracking to now")
                _reset_position_tracking()
            was_in_trading_session = in_trading_session

            # Interlocked with grid_bot: grid_bot trades only inside the
            # configured session window, so prediction_bot trades only
            # outside it — both can be left "active" at once without
            # colliding.
            enable = get_enable_status()
            gate_ok = (
                enable
                and latest_prediction_settings is not None
                and not in_trading_session
            )
            _set_computed_active(bool(gate_ok))
            logger.debug(
                f"[Prediction] Enable flag: {bool(enable)} "
                f"settings_loaded={latest_prediction_settings is not None} "
                f"in_trading_session={in_trading_session} -> {'run' if gate_ok else 'skip'}"
            )
            if gate_ok:
                effective_settings = _resolve_effective_settings(
                    primary_symbol, hedge_symbol, latest_prediction_settings
                )
                _process_tick(primary_symbol, effective_settings)
        except Exception as e:
            logger.error(f"[Prediction] Error in tick loop: {e}", exc_info=True)
        time.sleep(poll_interval)


def start_prediction_bot_sync():
    if os.environ.get('RUN_MAIN') != 'true':
        return

    try:
        PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
        primary_symbol = config.PAIRS[PAIR_INDEX]['primary']['symbol']
        hedge_symbol = config.PAIRS[PAIR_INDEX]['hedge']['symbol']
        logger.info(f"Starting prediction bot for {primary_symbol} ...")

        redis_conn = get_redis_connection()
        pubsub = redis_conn.pubsub()

        settings_channel = f"setting_prediction_channel:{primary_symbol}:{hedge_symbol}"
        pubsub.subscribe(settings_channel)
        logger.info(f"[Prediction] Subscribed to channel: [{settings_channel}]")

        threading.Thread(
            target=handle_prediction_flow,
            args=(pubsub, settings_channel, primary_symbol, hedge_symbol),
            daemon=True,
        ).start()
        logger.info("Prediction bot thread started and running in background.")
    except Exception as e:
        logger.error(f"Error while starting prediction bot: {e}", exc_info=True)
