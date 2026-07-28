import os
import logging
import time
import json
import threading
from app.utils.redis_client import get_redis_connection

from hyperliquid.info import Info
from hyperliquid.utils import constants

logger = logging.getLogger(__name__)
redis_conn = get_redis_connection()

BASE_URL = os.getenv("HYPERLIQUID_BASE_URL", constants.MAINNET_API_URL)

STALE_THRESHOLD = 30  # seconds without a message before reconnecting

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
    "No ticker" signal that price_diff/health checks rely on.
    """
    redis_key = f"ticker:hyperliquid:{symbol}"
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


def subscribe_symbol_ticker(symbol: str):
    _ensure_flusher(symbol)
    while True:
        info = None
        try:
            # skip_ws=False (default) starts the SDK's WebsocketManager thread.
            info = Info(BASE_URL, skip_ws=False)

            last_message_time = [time.time()]
            first_message_received = [False]

            def handle_message(message):
                try:
                    data = message.get("data", {})
                    # bbo is a 2-tuple: [best_bid_level, best_ask_level]; either
                    # side can be None when that book side is empty.
                    bbo = data.get("bbo") or []
                    bid = bbo[0] if len(bbo) > 0 else None
                    ask = bbo[1] if len(bbo) > 1 else None
                    if not bid or not ask:
                        return
                    # In-memory only — no network I/O here so the callback
                    # returns immediately and never backs up. The flush thread
                    # persists this to Redis on its own cadence.
                    _latest[symbol] = {
                        "best_bid": bid["px"],
                        "best_ask": ask["px"],
                        "event_ts": data.get("time"),
                    }
                    last_message_time[0] = time.time()
                    if not first_message_received[0]:
                        first_message_received[0] = True
                        logger.info(f"First ticker message received for {symbol} (hyperliquid).")
                except Exception as e:
                    logger.error(f"Error handling ticker message for {symbol}: {e}")

            info.subscribe({"type": "bbo", "coin": symbol}, handle_message)
            logger.info(f"WebSocket subscribed to bbo stream for {symbol} (hyperliquid).")

            # The SDK WebsocketManager has no auto-reconnect, so watch for a
            # stalled stream and recreate the connection — same pattern as the
            # Binance/Bybit ticker connectors.
            while True:
                time.sleep(5)
                elapsed = time.time() - last_message_time[0]
                if elapsed > STALE_THRESHOLD:
                    logger.warning(
                        f"No ticker message from hyperliquid for {symbol} in {elapsed:.0f}s. Reconnecting..."
                    )
                    break

        except Exception as e:
            logger.error(f"WebSocket error for {symbol}: {e}. Retrying in 1 second...")
            time.sleep(1)
        finally:
            if info is not None:
                try:
                    info.disconnect_websocket()
                except Exception as close_err:
                    logger.warning(f"Error closing WebSocket for {symbol}: {close_err}")


def get_ticker(symbol: str):
    redis_key = f"ticker:hyperliquid:{symbol}"
    ticker_raw = redis_conn.get(redis_key)
    if ticker_raw:
        ticker_data = json.loads(ticker_raw)
        return {
            "best_bid": ticker_data["best_bid"],
            "best_ask": ticker_data["best_ask"],
            "event_ts": float(ticker_data.get("event_ts", 0)),
        }
    return None


def fetch_ticker_data(symbol: str):
    threading.Thread(target=subscribe_symbol_ticker, args=(symbol,), daemon=True).start()
