import os
import logging
import asyncio
from app.utils.redis_client import get_redis_connection

from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL,
    ConfigurationWebSocketStreams,
)

logger = logging.getLogger(__name__)

configuration_ws_streams = ConfigurationWebSocketStreams(
    stream_url=os.getenv(
        "STREAM_URL", DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL
    )
)

client = DerivativesTradingUsdsFutures(config_ws_streams=configuration_ws_streams)
redis_conn = get_redis_connection()

async def subscribe_symbol_ticker(symbol: str):
    connection = None
    try:
        connection = await client.websocket_streams.create_connection()
        logger.info("WebSocket connection for symbol ticker established.")

        stream = await connection.individual_symbol_book_ticker_streams(
            symbol=symbol,
        )

        def handle_message(data):
            redis_key = f"ticker:{symbol}"
            redis_conn.hset(redis_key, mapping={"best_bid": data.b, "best_ask": data.a})
            logger.debug(f"Updated Redis {redis_key} -> Best Bid: {data.b}, Best Ask: {data.a}")

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

def get_ticker(symbol: str):
    redis_key = f"ticker:{symbol}"
    ticker_data = redis_conn.hgetall(redis_key)
    logger.debug(f"Fetched ticker data from Redis {redis_key}: {ticker_data}")
    if ticker_data:
        return {
            "best_bid": ticker_data.get(b'best_bid').decode('utf-8'),
            "best_ask": ticker_data.get(b'best_ask').decode('utf-8'),
        }
    return None