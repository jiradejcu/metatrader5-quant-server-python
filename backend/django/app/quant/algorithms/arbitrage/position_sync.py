import json
import time
import logging
import threading
from decimal import Decimal
from app.connectors.binance.api.position import get_position
from app.utils.redis_client import get_redis_connection

logger = logging.getLogger(__name__)

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
            time.sleep(0.1)

    except Exception as e:
        logger.error(f"Error processing position update for {symbol}: {e}", exc_info=True)

def start_position_sync():
    symbol = "PAXGUSDT"
    logger.info(f"Starting position sync for {symbol}...")

    try:
        redis_conn = get_redis_connection()
        pubsub = redis_conn.pubsub()
        pubsub.subscribe(f"position:{symbol}")
        logger.info(f"Subscribed to Redis channel position:{symbol} for position updates.")
        threading.Thread(target=handle_position_update, args=(pubsub,), daemon=True).start()       
    except Exception as e:
        logger.error(f"Error while syncing position for {symbol}: {e}", exc_info=True)
