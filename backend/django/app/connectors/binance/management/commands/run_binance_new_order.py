import os
import logging
import time
import asyncio
import threading
from dotenv import load_dotenv
from django.core.management.base import BaseCommand

from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    ConfigurationRestAPI,
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
)
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    NewOrderSideEnum,
    NewOrderTimeInForceEnum,
)

from . import run_binance_individual_symbol_ticker as ticker_stream

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

configuration_rest_api = ConfigurationRestAPI(
    api_key=os.environ.get('API_KEY_BINANCE'),
    api_secret=os.environ.get('API_SECRET_BINANCE'),
    base_path=os.getenv(
        "BASE_PATH", DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL
    ),
)

client = DerivativesTradingUsdsFutures(config_rest_api=configuration_rest_api)

def new_order(price):
    try:
        response = client.rest_api.new_order(
            symbol="paxgusdt",
            quantity=0.002,
            price=price,
            side=NewOrderSideEnum["BUY"].value,
            type="LIMIT",
            time_in_force=NewOrderTimeInForceEnum["GTC"].value,
        )

        rate_limits = response.rate_limits
        logging.info(f"new_order() rate limits: {rate_limits}")

        data = response.data()
        logging.info(f"new_order() response: {data}")
    except Exception as e:
        logging.error(f"new_order() error: {e}")


class Command(BaseCommand):
    def handle(self, *args, **options):
        logging.info(self.style.SUCCESS("Connecting to Binance WebSocket for ticker stream..."))

        websocket_thread = threading.Thread(target=asyncio.run,
                                            args=(ticker_stream.individual_symbol_book_ticker_streams(),),
                                            daemon=True)
        websocket_thread.start()

        try:
            while ticker_stream.BEST_BID is None or ticker_stream.BEST_ASK is None:
                logging.info("Waiting for BEST_BID and BEST_ASK to be set...")
                time.sleep(0.1)
            
            logging.info(self.style.SUCCESS("Placing new order on Binance..."))
            new_order(ticker_stream.BEST_BID)
        except KeyboardInterrupt:
            logging.error(self.style.ERROR("Keyboard Interrupt received."))
