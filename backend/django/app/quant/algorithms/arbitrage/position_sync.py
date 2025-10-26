import json
import time
import logging
import threading
from decimal import Decimal
from app.utils.redis_client import get_redis_connection
from app.utils.api.positions import get_position_by_symbol as get_mt5_position
from app.utils.api.order import send_market_order

logger = logging.getLogger(__name__)
symbol = "PAXGUSDT"
mt5_symbol = "XAUUSD"

def handle_position_update(pubsub):
    try:
        for message in pubsub.listen():
            if message['type'] == 'message':
                position_data = json.loads(message['data'])
                symbol = position_data.get('symbol')
                position_amt = Decimal(position_data.get('positionAmt', '0'))
                entry_price = Decimal(position_data.get('entryPrice', '0'))
                mark_price = Decimal(position_data.get('markPrice', '0'))
                unrealized_profit = Decimal(position_data.get('unRealizedProfit', '0'))

                logger.debug(
                    f"Position Update for {symbol} - "
                    f"Amount: {position_amt}, Entry Price: {entry_price}"
                    f", Mark Price: {mark_price}, Unrealized Profit: {unrealized_profit}"
                )
                
                mt5_position = get_mt5_position(mt5_symbol)
                
                mt5_volume = Decimal(str(mt5_position.get('volume', '0')))
                mt5_profit = Decimal(str(mt5_position.get('profit', '0')))

                logger.info(
                    f"MT5 Position for {mt5_symbol} - "
                    f"Volume: {mt5_volume}, Profit: {mt5_profit}"
                )
                
                order_amt = abs(position_amt - mt5_volume * Decimal('100'))
                if order_amt > Decimal('0.002'):
                    logger.info(
                        f"Discrepancy detected for {symbol}. "
                        f"Binance Amount: {position_amt}, MT5 Volume: {mt5_volume}. "
                        f"Placing order to adjust by {order_amt}."
                    )
                    send_market_order(
                        symbol=mt5_symbol,
                        volume=order_amt / Decimal('100'),
                        order_type='BUY' if position_amt > mt5_volume else 'SELL',
                        sl=float(entry_price * Decimal('0.9')),
                    )
                else:
                    logger.info(f"No significant discrepancy for {symbol}. No action taken.")
                
            time.sleep(0.1)

    except Exception as e:
        logger.error(f"Error processing position update for {symbol}: {e}", exc_info=True)

def start_position_sync():
    logger.info(f"Starting position sync for {symbol}...")

    try:
        redis_conn = get_redis_connection()
        pubsub = redis_conn.pubsub()
        pubsub.subscribe(f"position:{symbol}")
        logger.info(f"Subscribed to Redis channel position:{symbol} for position updates.")
        threading.Thread(target=handle_position_update, args=(pubsub,), daemon=True).start()       
    except Exception as e:
        logger.error(f"Error while syncing position for {symbol}: {e}", exc_info=True)
