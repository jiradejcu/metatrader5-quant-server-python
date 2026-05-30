import json
import time
import os
import logging
import threading
from . import config
from decimal import Decimal
from app.utils.redis_client import get_redis_connection
from app.utils.api.positions import get_position_by_symbol as get_hedge_position
from app.utils.api.order import send_market_order
from app.utils.position_group import update_position_group, resolve_group_id, make_comment, get_position_group

logger = logging.getLogger(__name__)

pre_order_volume = None
_prev_primary_entry_price = None


def _log_entry_price_diff(redis_conn, hedge_symbol: str, primary_entry: float, trigger: str):
    group = get_position_group(redis_conn, hedge_symbol)
    hedge_entry = float(group["entry_price"]) if group else 0.0
    if primary_entry == 0 or hedge_entry == 0:
        return
    diff = primary_entry - hedge_entry
    diff_pct = diff / hedge_entry * 100
    logger.info(
        "[EntryPriceDiff][%s] primary_entry=%.5f hedge_entry=%.5f diff=%.5f (%.3f%%)",
        trigger, primary_entry, hedge_entry, diff, diff_pct,
    )

def get_pause_status():
    redis_conn = get_redis_connection()
    redis_key= "position_sync_paused_flag"
    is_paused = redis_conn.get(redis_key)
    return is_paused

def handle_position_update(pubsub):
    global pre_order_volume, _prev_primary_entry_price
    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    primary_exchange = config.PAIRS[PAIR_INDEX]['primary']['exchange']
    hedge_exchange = config.PAIRS[PAIR_INDEX]['hedge']['exchange']
    contract_size = Decimal(config.PAIRS[PAIR_INDEX]['contract_size'])
    for message in pubsub.listen():
        try:
            is_pause = get_pause_status()
            if message['type'] == 'message' and is_pause is None:
                position_data = json.loads(message['data'])
                received_symbol = position_data.get('symbol')
                primary_symbol = config.PAIRS[PAIR_INDEX]['primary']['symbol']
                if received_symbol != primary_symbol:
                    logger.debug(f"Ignoring position update for symbol {received_symbol}. Expected {primary_symbol}.")
                    continue
                position_amt = Decimal(str(position_data.get('positionAmt', '0')))
                if os.getenv('MOCK_ENTRY_POSITION_AMT', 'false').lower() == 'true':
                    position_amt *= contract_size
                primary_entry_price = Decimal(str(position_data.get('entryPrice', '0')))
                primary_mark_price = Decimal(str(position_data.get('markPrice', '0')))
                primary_time_update = position_data.get('updateTime', None)

                logger.debug(
                    f"Primary Position {primary_exchange}:{primary_symbol} - "
                    f"Amount: {position_amt}, Entry Price: {primary_entry_price}, Mark Price: {primary_mark_price}, Update Time: {primary_time_update}"
                )

                hedge_symbol = config.PAIRS[PAIR_INDEX]['hedge']['symbol']

                if primary_entry_price != 0 and primary_entry_price != _prev_primary_entry_price:
                    _log_entry_price_diff(get_redis_connection(), hedge_symbol, float(primary_entry_price), "primary_fill")
                    _prev_primary_entry_price = primary_entry_price
                    
                hedge_position = get_hedge_position(hedge_symbol)
                hedge_volume = Decimal(str(hedge_position.get('volume', '0')))
                hedge_entry_price = Decimal(str(hedge_position.get('entryPrice', '0')))
                hedge_mark_price = Decimal(str(hedge_position.get('markPrice', '0')))
                hedge_time_update = hedge_position.get('time_update', None)

                if pre_order_volume is not None:
                    if hedge_volume == pre_order_volume:
                        logger.debug(f"Hedge volume unchanged at {hedge_volume}. Waiting for MT5 position update...")
                        continue
                    logger.debug(f"MT5 position confirmed: {pre_order_volume} → {hedge_volume}.")
                    pre_order_volume = None

                logger.debug(
                    f"Hedge Position {hedge_exchange}:{hedge_symbol} - "
                    f"Volume: {hedge_volume}, Entry Price: {hedge_entry_price}, "
                    f"Mark Price: {hedge_mark_price}, Time Update: {hedge_time_update}"
                )

                # Compare actual mark-price spread with the latest ticker-based price_diff
                if primary_mark_price > 0 and hedge_mark_price > 0:
                    redis_conn = get_redis_connection()
                    primary_symbol_key = config.PAIRS[PAIR_INDEX]['primary']['symbol']
                    price_diff_raw = redis_conn.get(f"price_diff:{primary_symbol_key}:{hedge_symbol}")
                    if price_diff_raw:
                        price_diff_data = json.loads(price_diff_raw)
                        ticker_ask_diff = price_diff_data.get('ask_diff', 0)
                        ticker_bid_diff = price_diff_data.get('bid_diff', 0)
                        mark_diff = float(primary_mark_price - hedge_mark_price)
                        logger.debug(
                            f"Spread comparison [{primary_symbol_key}/{hedge_symbol}]: "
                            f"mark_diff={mark_diff:.2f} "
                            f"(primary_mark={float(primary_mark_price):.2f}, hedge_mark={float(hedge_mark_price):.2f}) "
                            f"| ticker ask_diff={ticker_ask_diff}, bid_diff={ticker_bid_diff} "
                            f"| Δask={mark_diff - ticker_ask_diff:.2f}, Δbid={mark_diff - ticker_bid_diff:.2f}"
                        )

                discrepancy = position_amt + hedge_volume * contract_size

                logger.debug(
                    f"Primary Amount: {position_amt}, Hedge Volume: {hedge_volume}. "
                    f"Position Size Difference: {discrepancy}."
                )

                order_amt = Decimal(int(-discrepancy))

                if abs(order_amt) >= Decimal('1.00'):
                    logger.info(
                        f"Discrepancy detected for {received_symbol}. "
                        f"Placing order to adjust by {order_amt}."
                    )

                    # ── Resolve position group ID before placing the order ──
                    # is_new_position is True when the hedge has no open volume
                    # yet — this order starts a brand-new position lifecycle.
                    expected_hedge_volume = (
                        float(hedge_volume)
                        + float(order_amt) / float(contract_size)
                    )
                    is_opening = abs(expected_hedge_volume) > abs(float(hedge_volume))
                    is_new_position = abs(float(hedge_volume)) < 1e-9 and is_opening

                    redis_conn = get_redis_connection()
                    group_id = resolve_group_id(
                        redis_conn=redis_conn,
                        symbol=hedge_symbol,
                        is_new_position=is_new_position,
                    )
                    # ──────────────────────────────────────────────────────

                    order = send_market_order(
                        symbol=hedge_symbol,
                        volume=abs(order_amt / contract_size),
                        order_type='BUY' if order_amt > 0 else 'SELL',
                        # Embed group_id in MT5 ticket comment for durable
                        # group membership — survives Redis restarts.
                        comment=make_comment(group_id),
                    )

                    if order:
                        fill_price = float(order.get('price', 0))
                        fill_volume = abs(float(order.get('volume', 0)))

                        if fill_price > 0 and fill_volume > 0:
                            redis_conn = get_redis_connection()
                            update_position_group(
                                redis_conn=redis_conn,
                                symbol=hedge_symbol,
                                fill_price=fill_price,
                                fill_volume=fill_volume,
                                is_opening=is_opening,
                                group_id=group_id,
                            )
                            _log_entry_price_diff(redis_conn, hedge_symbol, float(primary_entry_price), "hedge_fill")

                        pre_order_volume = hedge_volume
                        redis_conn = get_redis_connection()
                        redis_conn.delete(f"position:mt5:{hedge_symbol}")
                else:
                    logger.debug(f"No significant discrepancy for {received_symbol}. No action taken.")

            time.sleep(0.1)

        except Exception as e:
            logger.error(f"Error processing position update: {e}", exc_info=True)

def start_position_sync():
    if os.environ.get('RUN_MAIN') != 'true':
        return

    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    primary_exchange = config.PAIRS[PAIR_INDEX]['primary']['exchange']
    primary_symbol = config.PAIRS[PAIR_INDEX]['primary']['symbol']
    logger.info(f"Starting position sync for {primary_symbol}...")

    try:
        redis_conn = get_redis_connection()
        pubsub = redis_conn.pubsub()
        pubsub.subscribe(f"position:{primary_exchange}:{primary_symbol}")
        logger.info(f"Subscribed to Redis channel position:{primary_exchange}:{primary_symbol} for position updates.")
        threading.Thread(target=handle_position_update, args=(pubsub,), daemon=True).start()
    except Exception as e:
        logger.error(f"Error while syncing position for {primary_symbol}: {e}", exc_info=True)
