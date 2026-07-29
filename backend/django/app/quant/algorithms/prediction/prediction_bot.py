import json
import logging
import math
import os
import threading
import time

from app.utils.redis_client import get_redis_connection
from app.connectors.binance.api.order import close_order
from app.connectors.binance.api.position import get_position
from app.connectors.binance.api.ticker import get_ticker
from app.connectors.binance.api.depth import get_order_book
from ..arbitrage import config
from ..trading_sessions import is_within_trading_session

logger = logging.getLogger(__name__)

latest_prediction_settings = None

QTY_PRECISION = int(os.getenv('PREDICTION_QTY_PRECISION', '3'))


def _parse_prediction_settings(settings_dict):
    return {
        "profit_target_usd": float(settings_dict.get('profit_target_usd', 0.0)),
        "max_slippage_usd": float(settings_dict.get('max_slippage_usd', 0.0)),
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


def _process_tick(primary_symbol, settings):
    """Execute one prediction-bot decision. This bot never opens positions —
    the grid bot is responsible for entries. It only watches for an existing
    long position and closes it once the profit target is met.
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
