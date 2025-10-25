import os
import logging
import time
import json
import asyncio
from dotenv import load_dotenv
from django.core.management.base import BaseCommand
from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL,
    ConfigurationWebSocketStreams,
)

load_dotenv()
api_key = os.environ.get('API_KEY_BINANCE')
api_secret = os.environ.get('API_SECRET_BINANCE')

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

configuration_ws_streams = ConfigurationWebSocketStreams(
    stream_url=os.getenv(
        "STREAM_URL", DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL
    )
)

client = DerivativesTradingUsdsFutures(config_ws_streams=configuration_ws_streams)

async def all_book_tickers_stream():
    connection = None
    try:
        connection = await client.websocket_streams.create_connection()

        stream = await connection.all_book_tickers_stream()
        stream.on("message", lambda data: print(f"{data}"))

        await asyncio.sleep(5)
        await stream.unsubscribe()
    except Exception as e:
        logging.error(f"all_book_tickers_stream() error: {e}")
    finally:
        if connection:
            await connection.close_connection(close_session=True)


class Command(BaseCommand):
    help = 'Connects to Binance USD-M Futures WebSocket and subscribes to the all book tickers stream.'

    def handle(self, *args, **options):
        logger.info(self.style.SUCCESS("Connecting to Binance WebSocket..."))
        try:
            asyncio.run(all_book_tickers_stream())
        except KeyboardInterrupt:
            logging.error(self.style.ERROR("Keyboard Interrupt received. Closing WebSocket connection."))
            logging.error(self.style.ERROR("Connection closed."))
