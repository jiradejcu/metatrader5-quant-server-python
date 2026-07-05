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

# How often the flush thread writes the latest tick to Redis (seconds).
FLUSH_INTERVAL = float(os.getenv("TICKER_FLUSH_INTERVAL", "0.05"))

# Latest tick per symbol, updated in-memory by the WebSocket callback. Kept out
# of Redis on the hot path so the callback never blocks on network I/O and the
# socket always drains at memory speed (no receive-buffer backlog / stale ages).
_latest = {}
_flusher_started = set()
_flusher_lock = threading.Lock()


def _flush_latest_to_redis(symbol: str):
    """Write the most recent in-memory tick to Redis at a fixed cadence.

    Only writes when a new tick has arrived (event_ts changed), so a dead stream
    stops refreshing the key and it TTL-expires after 10s — preserving the
    "No primary ticker" signal that price_diff/health checks rely on.
    """
    redis_key = f"ticker:binance:{symbol}"
    last_flushed_ts = None
    while True:
        time.sleep(FLUSH_INTERVAL)
        payload = _latest.get(symbol)
        if payload is None or payload["event_ts"] == last_flushed_ts:
            continue
        try:
            redis_conn.set(redis_key, json.dumps(payload), ex=10)
            last_flushed_ts = payload["event_ts"]
        except Exception as e:
            logger.error(f"Error flushing {symbol} ticker to Redis: {e}")


def _ensure_flusher(symbol: str):
    """Start the Redis flush thread for a symbol exactly once."""
    with _flusher_lock:
        if symbol in _flusher_started:
            return
        _flusher_started.add(symbol)
    threading.Thread(target=_flush_latest_to_redis, args=(symbol,), daemon=True).start()
    logger.info(f"Started Redis flush thread for {symbol} ticker (interval={FLUSH_INTERVAL * 1000:.0f}ms).")


async def subscribe_symbol_ticker(symbol: str):
    _ensure_flusher(symbol)
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
                # In-memory only — no network I/O here so the callback returns
                # immediately and the WebSocket never accumulates a backlog.
                # The flush thread persists this to Redis on its own cadence.
                _latest[symbol] = {"best_bid": data.b, "best_ask": data.a, "event_ts": data.E}
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
    ticker_raw = redis_conn.get(redis_key)
    # logger.debug(f"Fetched ticker data from Redis {redis_key}: {ticker_raw}")
    if ticker_raw:
        ticker_data = json.loads(ticker_raw)
        return {
            "best_bid": ticker_data["best_bid"],
            "best_ask": ticker_data["best_ask"],
            "event_ts": float(ticker_data.get("event_ts", 0)),
        }
    return None


def fetch_ticker_data(symbol: str):
    threading.Thread(target=asyncio.run, args=(subscribe_symbol_ticker(symbol),), daemon=True).start()