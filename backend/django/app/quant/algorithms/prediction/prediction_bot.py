import json
import logging
import math
import os
import threading
import time
from datetime import datetime, timezone

from app.utils.redis_client import get_redis_connection
from app.connectors.binance.api.order import (
    get_open_orders,
    cancel_all_open_orders,
    chase_order,
    close_order,
)
from app.connectors.binance.api.position import get_position
from app.connectors.binance.api.ticker import get_ticker
from app.connectors.binance.api.depth import get_order_book
from ..arbitrage import config

logger = logging.getLogger(__name__)

latest_prediction_settings = None

_DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

QTY_PRECISION = int(os.getenv('PREDICTION_QTY_PRECISION', '3'))


def _parse_prediction_settings(settings_dict):
    return {
        "minutes_before_close": float(settings_dict.get('minutes_before_close', 0.0)),
        "order_amount": float(settings_dict.get('order_amount', 0.0)),
        "profit_target_usd": float(settings_dict.get('profit_target_usd', 0.0)),
        "max_slippage_usd": float(settings_dict.get('max_slippage_usd', 0.0)),
    }


def _minutes_until_session_close(sessions, now_utc):
    """Return minutes remaining until the end of the currently active trading
    session, or None if `now_utc` doesn't fall inside any configured range.

    Uses the same Redis schema as grid_bot._is_within_trading_session:
    {day_name: [{"start": "HH:MM", "end": "HH:MM"}]}, where "24:00" means end
    of day. No config at all means no session boundary is defined, so there's
    nothing to count down to.
    """
    if not sessions:
        return None

    day_name = _DAY_NAMES[now_utc.weekday()]
    ranges = sessions.get(day_name, [])
    current_minutes = now_utc.hour * 60 + now_utc.minute + now_utc.second / 60

    for r in ranges:
        start_h, start_m = map(int, r['start'].split(':'))
        end_h, end_m = map(int, r['end'].split(':'))
        start_min = start_h * 60 + start_m
        end_min = end_h * 60 + end_m
        if start_min <= current_minutes < end_min:
            return end_min - current_minutes

    return None


def _is_entry_window(minutes_remaining, minutes_before_close):
    if minutes_remaining is None or minutes_before_close <= 0:
        return False
    return minutes_remaining <= minutes_before_close


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


def _get_trading_sessions(primary_symbol, hedge_symbol):
    try:
        redis_conn = get_redis_connection()
        raw = redis_conn.get(f"trading_sessions:{primary_symbol}:{hedge_symbol}")
        return json.loads(raw) if raw else None
    except Exception as e:
        logger.warning(f"[Prediction] Failed to read trading sessions: {e}")
        return None


def _already_entered_today(primary_symbol, hedge_symbol):
    redis_conn = get_redis_connection()
    key = f"prediction_entered_date:{primary_symbol}:{hedge_symbol}"
    raw = redis_conn.get(key)
    if raw is None:
        return False
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return raw.decode('utf-8') == today


def _mark_entered_today(primary_symbol, hedge_symbol):
    redis_conn = get_redis_connection()
    key = f"prediction_entered_date:{primary_symbol}:{hedge_symbol}"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    redis_conn.set(key, today, ex=172800)  # 2 days — self-cleaning, tomorrow's date won't match anyway


def get_active_status():
    return get_redis_connection().get("prediction_bot_active_flag")


def _handle_idle(primary_symbol, hedge_symbol, settings):
    if settings['order_amount'] <= 0:
        logger.debug("[Prediction] order_amount not configured — skipping")
        return

    if _already_entered_today(primary_symbol, hedge_symbol):
        return

    sessions = _get_trading_sessions(primary_symbol, hedge_symbol)
    minutes_remaining = _minutes_until_session_close(sessions, datetime.now(timezone.utc))

    if not _is_entry_window(minutes_remaining, settings['minutes_before_close']):
        return

    logger.info(
        f"[Prediction] Entry window open ({minutes_remaining:.1f}m to session close) — "
        f"placing best-bid BUY for {settings['order_amount']} on {primary_symbol}"
    )
    chase_order(primary_symbol, settings['order_amount'], 'BUY', order_id=None)
    _mark_entered_today(primary_symbol, hedge_symbol)


def _handle_entering(primary_symbol, hedge_symbol, open_orders, settings):
    sessions = _get_trading_sessions(primary_symbol, hedge_symbol)
    minutes_remaining = _minutes_until_session_close(sessions, datetime.now(timezone.utc))
    if minutes_remaining is None:
        logger.info("[Prediction] Trading session ended before entry filled — cancelling")
        cancel_all_open_orders(primary_symbol)
        return

    order = open_orders[0]
    side = getattr(order, 'side', None)
    if side != 'BUY':
        logger.warning(f"[Prediction] Unexpected {side} order while entering — cancelling")
        cancel_all_open_orders(primary_symbol)
        return

    order_id = getattr(order, 'order_id', None)
    qty = float(getattr(order, 'orig_qty', settings['order_amount']))
    logger.debug(f"[Prediction] Chasing entry order_id={order_id} qty={qty}")
    chase_order(primary_symbol, qty, 'BUY', order_id=order_id)


def _handle_holding_or_closing(primary_symbol, position_amt, position, settings):
    entry_price = float((position or {}).get('entryPrice', 0) or 0)
    ticker = get_ticker(primary_symbol)
    if not ticker or not entry_price:
        return

    profit_usd = ticker['best_bid'] - entry_price
    if profit_usd < settings['profit_target_usd']:
        logger.debug(
            f"[Prediction] Holding {position_amt} {primary_symbol}: "
            f"profit={profit_usd:.2f} < target={settings['profit_target_usd']:.2f}"
        )
        return

    order_book = get_order_book(primary_symbol)
    bids = (order_book or {}).get('bids', [])
    close_qty, worst_price = _max_closeable_qty(bids, position_amt, settings['max_slippage_usd'])
    close_qty = _round_down(close_qty)

    if close_qty <= 0 or worst_price is None:
        logger.debug(
            f"[Prediction] Profit target hit (profit={profit_usd:.2f}) but book too thin to close "
            f"within slippage budget ({settings['max_slippage_usd']}) — waiting"
        )
        return

    logger.info(
        f"[Prediction] Closing {close_qty}/{position_amt} {primary_symbol} at worst_price={worst_price} "
        f"(profit={profit_usd:.2f}, slippage_budget={settings['max_slippage_usd']})"
    )
    close_order(primary_symbol, close_qty, 'SELL', worst_price)


def _process_tick(primary_symbol, hedge_symbol, settings):
    """Execute one prediction-bot decision. Phase is derived from live
    exchange state each tick rather than tracked separately, so a restart
    just resumes wherever the actual position/orders are.
    """
    position = get_position(primary_symbol)
    position_amt = float((position or {}).get('positionAmt', 0) or 0)

    if position_amt < 0:
        logger.warning(
            f"[Prediction] Unexpected short position {position_amt} on {primary_symbol} — "
            "this algorithm only manages longs, skipping tick"
        )
        return

    if position_amt > 0:
        _handle_holding_or_closing(primary_symbol, position_amt, position, settings)
        return

    open_orders = get_open_orders(primary_symbol)
    if open_orders:
        _handle_entering(primary_symbol, hedge_symbol, open_orders, settings)
        return

    _handle_idle(primary_symbol, hedge_symbol, settings)


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
            if get_active_status() and latest_prediction_settings is not None:
                _process_tick(primary_symbol, hedge_symbol, latest_prediction_settings)
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
