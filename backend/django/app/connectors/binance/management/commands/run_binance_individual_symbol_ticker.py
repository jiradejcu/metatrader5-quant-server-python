import os
import logging
import asyncio
from django.core.management.base import BaseCommand

from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL,
    ConfigurationWebSocketStreams,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

configuration_ws_streams = ConfigurationWebSocketStreams(
    stream_url=os.getenv(
        "STREAM_URL", DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL
    )
)

client = DerivativesTradingUsdsFutures(config_ws_streams=configuration_ws_streams)

BEST_BID = None
BEST_ASK = None

async def individual_symbol_book_ticker_streams():
    connection = None
    try:
        connection = await client.websocket_streams.create_connection()

        stream = await connection.individual_symbol_book_ticker_streams(
            symbol="paxgusdt",
        )

        def handle_message(data):
            global BEST_BID, BEST_ASK
            BEST_BID = data.b  # Best bid price
            BEST_ASK = data.a  # Best ask price
            logger.info(f"Best Bid: {BEST_BID}, Best Ask: {BEST_ASK}")

        stream.on("message", handle_message)

        while True:
            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info("WebSocket task cancelled. Closing connection.")
    except Exception as e:
        logger.error(f"individual_symbol_book_ticker_streams() error: {e}")
    finally:
        if connection:
            logger.info("Closing WebSocket connection...")
            await connection.close_connection(close_session=True)


class Command(BaseCommand):
    def handle(self, *args, **options):
        logger.info(self.style.SUCCESS("Connecting to Binance WebSocket for individual symbol ticker streams..."))
        asyncio.run(individual_symbol_book_ticker_streams())
