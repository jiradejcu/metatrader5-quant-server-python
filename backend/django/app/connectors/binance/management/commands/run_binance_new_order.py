import logging
import time
from django.core.management.base import BaseCommand
from app.connectors.binance.api.order import new_order
from app.connectors.binance.api.ticker import get_ticker

logger = logging.getLogger(__name__)

symbol = "PAXGUSDT"

class Command(BaseCommand):
    def handle(self, *args, **options):
        logger.info(f"Attempting to place a test order for {symbol}...")
        
        try:
            for _ in range(20):
                ticker_data = get_ticker(symbol)
                if ticker_data:
                    break
                logger.info(f"Waiting for ticker data for {symbol} in Redis...")
                time.sleep(0.5)

            price_to_buy = ticker_data['best_bid']
            logger.info(f"Found best bid price: {price_to_buy}. Placing new order on Binance...")
            
            new_order(symbol, 0.002, price_to_buy, 'BUY')
            logger.info("Order command sent successfully.")
        except KeyboardInterrupt:
            logger.error("Command cancelled by user.")
        except Exception as e:
            logger.error(f"An error occurred: {e}")
