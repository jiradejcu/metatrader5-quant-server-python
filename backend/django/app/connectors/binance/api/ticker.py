import os
import logging
import asyncio
import json
import time
from app.utils.redis_client import get_redis_connection
import threading

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
    while True:
        connection = None
        try:
            connection = await client.websocket_streams.create_connection()
            logger.info(f"WebSocket connection for {symbol} ticker established.")

            stream = await connection.individual_symbol_book_ticker_streams(
                symbol=symbol,
            )

            last_message_time = [time.time()]
            first_message_received = [False]

            def handle_message(data):
                redis_key = f"ticker:binance:{symbol}"
                redis_conn.hset(redis_key, mapping={"best_bid": data.b, "best_ask": data.a})
                redis_conn.expire(redis_key, 10)
                last_message_time[0] = time.time()
                if not first_message_received[0]:
                    first_message_received[0] = True
                    logger.info(f"First ticker message received for {symbol} (binance).")

            stream.on("message", handle_message)

            STALE_THRESHOLD = 30

            while True:
                await asyncio.sleep(5)
                elapsed = time.time() - last_message_time[0]
                if elapsed > STALE_THRESHOLD:
                    logger.warning(
                        f"No ticker message from binance for {symbol} in {elapsed:.0f}s. Reconnecting..."
                    )
                    break

        except asyncio.CancelledError:
            logger.error(f"WebSocket task for {symbol} cancelled. Closing connection.")
            break
        except Exception as e:
            logger.error(f"WebSocket error for {symbol}: {e}. Retrying in 1 seconds...")
            await asyncio.sleep(1)
        finally:
            if connection:
                try:
                    logger.warning(f"Closing WebSocket connection for {symbol}...")
                    await connection.close_connection(close_session=True)
                except Exception as close_err:
                    logger.warning(f"Error while closing connection for {symbol}: {close_err}")

def get_ticker(symbol: str):
    redis_key = f"ticker:binance:{symbol}"
    ticker_data = redis_conn.hgetall(redis_key)
    # logger.debug(f"Fetched ticker data from Redis {redis_key}: {ticker_data}")
    if ticker_data:
        return {
            "best_bid": ticker_data.get(b'best_bid').decode('utf-8'),
            "best_ask": ticker_data.get(b'best_ask').decode('utf-8'),
        }
    return None


def fetch_ticker_data(symbol: str):
    threading.Thread(target=asyncio.run, args=(subscribe_symbol_ticker(symbol),), daemon=True).start()