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
from ..trading_sessions import is_within_trading_session

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
    }


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


def get_active_status():
    return get_redis_connection().get("prediction_bot_active_flag")


def _close_passive(primary_symbol, position_amt, open_orders):
    """Chase a post-only best-ask SELL, same order style as grid_bot's entries."""
    if not open_orders:
        logger.info(
            f"[Prediction] Placing passive best-ask SELL for {position_amt} on {primary_symbol}"
        )
        chase_order(primary_symbol, position_amt, 'SELL', order_id=None)
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


def _close_aggressive(primary_symbol, position_amt, open_orders, max_slippage_usd):
    """Cross the book with a reduce-only IOC SELL bounded by max_slippage_usd."""
    if open_orders:
        # A resting passive order can only get here if aggressiveness was just
        # switched mid-flight — pull it so the two styles don't stack.
        logger.info("[Prediction] Switching to aggressive close — cancelling resting order first")
        cancel_all_open_orders(primary_symbol)
        return

    order_book = get_order_book(primary_symbol)
    bids = (order_book or {}).get('bids', [])
    close_qty, worst_price = _max_closeable_qty(bids, position_amt, max_slippage_usd)
    close_qty = _round_down(close_qty)

    if close_qty <= 0 or worst_price is None:
        logger.debug(
            f"[Prediction] Aggressive close: book too thin to close within slippage budget "
            f"({max_slippage_usd}) — waiting"
        )
        return

    logger.info(
        f"[Prediction] Aggressive close {close_qty}/{position_amt} {primary_symbol} at worst_price={worst_price} "
        f"(slippage_budget={max_slippage_usd})"
    )
    close_order(primary_symbol, close_qty, 'SELL', worst_price)


def _handle_holding_or_closing(primary_symbol, position_amt, position, open_orders, settings):
    entry_price = float((position or {}).get('entryPrice', 0) or 0)
    ticker = get_ticker(primary_symbol)
    if not ticker or not entry_price:
        return

    profit_usd = ticker['best_bid'] - entry_price
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
        _close_aggressive(primary_symbol, position_amt, open_orders, settings['max_slippage_usd'])
    else:
        _close_passive(primary_symbol, position_amt, open_orders)


def _process_tick(primary_symbol, settings):
    """Execute one prediction-bot decision. This bot never opens positions —
    the grid bot is responsible for entries. It only watches for an existing
    long position and closes it once the profit target is met, using either
    the "passive" or "aggressive" order style per settings['aggressiveness'].
    """
    position = get_position(primary_symbol)
    position_amt = float((position or {}).get('positionAmt', 0) or 0)

    if position_amt < 0:
        logger.warning(
            f"[Prediction] Unexpected short position {position_amt} on {primary_symbol} — "
            "this algorithm only manages longs, skipping tick"
        )
        return

    open_orders = get_open_orders(primary_symbol)

    if position_amt > 0:
        _handle_holding_or_closing(primary_symbol, position_amt, position, open_orders, settings)
        return

    if open_orders:
        logger.info("[Prediction] No position but open order(s) found — cancelling")
        cancel_all_open_orders(primary_symbol)


def handle_prediction_flow(pubsub, settings_channel, primary_symbol, hedge_symbol, poll_interval=2.0):
    global latest_prediction_settings
    latest_prediction_settings = None

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
            # Interlocked with grid_bot: grid_bot trades only inside the
            # configured session window, so prediction_bot trades only
            # outside it — both can be left "active" at once without
            # colliding.
            if (
                get_active_status()
                and latest_prediction_settings is not None
                and not is_within_trading_session(primary_symbol, hedge_symbol)
            ):
                _process_tick(primary_symbol, latest_prediction_settings)
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
