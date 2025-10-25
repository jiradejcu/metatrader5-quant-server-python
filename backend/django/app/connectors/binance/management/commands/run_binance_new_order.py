import logging
import time
import asyncio
import threading
from django.core.management.base import BaseCommand
import app.connectors.binance.api.ticker as ticker_stream
from app.connectors.binance.api.order import new_order

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

symbol = "PAXGUSDT"

class Command(BaseCommand):
    def handle(self, *args, **options):
        logging.info(self.style.SUCCESS("Connecting to Binance WebSocket for ticker stream..."))

        websocket_thread = threading.Thread(target=asyncio.run,
                                            args=(ticker_stream.subscribe_symbol_ticker(symbol),),
                                            daemon=True)
        websocket_thread.start()

        try:
            while ticker_stream.BEST_BID is None or ticker_stream.BEST_ASK is None:
                logging.info("Waiting for BEST_BID and BEST_ASK to be set...")
                time.sleep(0.1)
            
            logging.info(self.style.SUCCESS("Placing new order on Binance..."))
            new_order(symbol, 0.002, ticker_stream.BEST_BID, 'BUY')
        except KeyboardInterrupt:
            logging.error(self.style.ERROR("Keyboard Interrupt received."))
