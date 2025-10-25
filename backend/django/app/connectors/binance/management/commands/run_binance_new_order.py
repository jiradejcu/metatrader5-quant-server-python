import logging
import time
from django.core.management.base import BaseCommand
from app.connectors.binance.api.order import new_order
from app.connectors.redis_client import get_redis_connection

logger = logging.getLogger(__name__)

symbol = "PAXGUSDT"

class Command(BaseCommand):
    def handle(self, *args, **options):
        logger.info(f"Attempting to place a test order for {symbol}...")

        try:
            redis_conn = get_redis_connection()
            redis_key = f"ticker:{symbol}"

            for _ in range(20):
                ticker_data = redis_conn.hgetall(redis_key)
                if ticker_data:
                    break
                logger.info(f"Waiting for ticker data in Redis key '{redis_key}'...")
                time.sleep(0.5)

            price_to_buy = ticker_data.get(b'best_bid')
            if not price_to_buy:
                logger.error(f"Could not find 'best_bid' price in Redis for {symbol}. Aborting.")
                return

            price_str = price_to_buy.decode('utf-8')
            logger.info(f"Found best bid price: {price_str}. Placing new order on Binance...")
            new_order(symbol, 0.002, price_str, 'BUY')
            logger.info("Order command sent successfully.")
        except KeyboardInterrupt:
            logger.error("Command cancelled by user.")
        except Exception as e:
            logger.error(f"An error occurred: {e}")
