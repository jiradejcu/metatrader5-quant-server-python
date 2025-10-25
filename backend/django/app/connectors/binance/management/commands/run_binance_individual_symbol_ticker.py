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

async def individual_symbol_ticker_streams():
    connection = None
    try:
        connection = await client.websocket_streams.create_connection()

        stream = await connection.individual_symbol_ticker_streams(
            symbol="paxgusdt",
        )
        stream.on("message", lambda data: print(f"{data}"))

        while True:
            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logging.info("WebSocket task cancelled. Closing connection.")
    except Exception as e:
        logging.error(f"individual_symbol_ticker_streams() error: {e}")
    finally:
        if connection:
            logging.info("Closing WebSocket connection...")
            await connection.close_connection(close_session=True)


class Command(BaseCommand):
    def handle(self, *args, **options):
        logger.info(self.style.SUCCESS("Connecting to Binance WebSocket for individual symbol ticker streams..."))
        asyncio.run(individual_symbol_ticker_streams())
