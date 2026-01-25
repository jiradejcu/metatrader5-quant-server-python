import json
import time
import os
import logging
import threading
from . import config
from decimal import Decimal
from app.utils.redis_client import get_redis_connection
from app.utils.api.positions import get_position_by_symbol as get_mt5_position
from app.utils.api.order import send_market_order

logger = logging.getLogger(__name__)
# contract_size = Decimal('100')

latest_update = None

def get_pause_status():
    redis_conn = get_redis_connection()
    redis_key= "position_sync_paused_flag"
    is_paused = redis_conn.get(redis_key)
    return is_paused

def handle_position_update(pubsub):
    global latest_update
    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    contract_size = Decimal(os.getenv('CONTRACT_SIZE'))
    try:
        for message in pubsub.listen():
            is_pause = get_pause_status()
            # If the condition is true, position sync logic is running
            if message['type'] == 'message' and is_pause is None:
                logger.debug('Position_sync is runing!!')
                position_data = json.loads(message['data'])
                received_symbol = position_data.get('symbol')
                config_symbol = config.PAIRS[PAIR_INDEX]['binance']
                if received_symbol != config_symbol:
                    logger.debug(f"Ignoring position update for symbol {received_symbol}. Expected {config_symbol}.")
                    continue
                position_amt = Decimal(str(position_data.get('positionAmt', '0')))
                # position_amt = Decimal(str(position_data.get('positionAmt', '0'))) * contract_size # mock up Binance position amount
                entry_price = Decimal(str(position_data.get('entryPrice', '0')))
                mark_price = Decimal(str(position_data.get('markPrice', '0')))
                unrealized_profit = Decimal(str(position_data.get('unRealizedProfit', '0')))

                logger.debug(
                    f"Binance Position for {received_symbol} - "
                    f"Amount: {position_amt}, Entry Price: {entry_price}"
                    f", Mark Price: {mark_price}, Unrealized Profit: {unrealized_profit}"
                )
                
                mt5_symbol = config.PAIRS[PAIR_INDEX]['mt5']
                mt5_position = get_mt5_position(mt5_symbol)
                
                mt5_volume = Decimal(str(mt5_position.get('volume', '0')))
                mt5_time_update = mt5_position.get('time_update', None)
                
                if latest_update is not None:
                    if mt5_time_update is None or latest_update >= mt5_time_update:
                        logger.debug("No position information update from MT5. Skipping...")
                        continue
                    else:
                        logger.debug("New position information from MT5. Reset latest update.")
                        latest_update = None

                logger.debug(
                    f"MT5 Position for {mt5_symbol} - "
                    f"Volume: {mt5_volume}"
                    f", Time Update: {mt5_time_update}"
                )
                
                discrepancy = position_amt + mt5_volume * contract_size
                
                logger.debug(
                    f"Binance Amount: {position_amt}, MT5 Volume: {mt5_volume}. "
                    f"Position Size Difference: {discrepancy}."
                )
                
                order_amt = Decimal(int(-discrepancy))
                
                if abs(order_amt) >= Decimal('1.00'):
                    logger.info(
                        f"Discrepancy detected for {received_symbol}. "
                        f"Placing order to adjust by {order_amt}."
                    )
                    
                    order = send_market_order(
                        symbol=mt5_symbol,
                        volume=abs(order_amt / contract_size),
                        order_type='BUY' if order_amt > 0 else 'SELL',
                    )
                    
                    if order:
                        latest_update = mt5_time_update
                else:
                    logger.debug(f"No significant discrepancy for {received_symbol}. No action taken.")
                
            time.sleep(0.1)

    except Exception as e:
        logger.error(f"Error processing position update: {e}", exc_info=True)

def start_position_sync():
    if os.environ.get('RUN_MAIN') != 'true':
        return
    
    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    symbol = config.PAIRS[PAIR_INDEX]['binance']
    logger.info(f"Starting position sync for {symbol}...")

    try:
        redis_conn = get_redis_connection()
        pubsub = redis_conn.pubsub()
        pubsub.subscribe(f"position:{symbol}")
        logger.info(f"Subscribed to Redis channel position:{symbol} for position updates.")
        threading.Thread(target=handle_position_update, args=(pubsub,), daemon=True).start()       
    except Exception as e:
        logger.error(f"Error while syncing position for {symbol}: {e}", exc_info=True)
