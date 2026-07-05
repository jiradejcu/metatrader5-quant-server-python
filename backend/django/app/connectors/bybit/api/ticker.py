import os
import logging
import time
import json
import threading
from pybit.unified_trading import WebSocket
from app.utils.redis_client import get_redis_connection

logger = logging.getLogger(__name__)
redis_conn = get_redis_connection()


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

    Dedups on a per-message sequence number, so the key is refreshed while the
    stream delivers messages and TTL-expires after 10s once it goes silent —
    preserving the "No ticker" signal that price_diff/health checks rely on.
    """
    redis_key = f"ticker:bybit:{symbol}"
    last_seq = None
    while True:
        time.sleep(FLUSH_INTERVAL)
        latest = _latest.get(symbol)
        if latest is None or latest["seq"] == last_seq:
            continue
        try:
            payload = json.dumps({"best_bid": latest["best_bid"], "best_ask": latest["best_ask"]})
            redis_conn.set(redis_key, payload, ex=10)
            last_seq = latest["seq"]
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
        ws = None
        try:
            ws = WebSocket(testnet=False, channel_type="linear")

            last_message_time = [time.time()]
            first_message_received = [False]

            def handle_message(data):
                try:
                    ob_data = data.get('data', {})
                    bids = ob_data.get('b', [])
                    asks = ob_data.get('a', [])
                    if bids and asks:
                        # In-memory only — no network I/O here so the callback
                        # returns immediately and never backs up. The flush
                        # thread persists this to Redis on its own cadence.
                        prev = _latest.get(symbol)
                        seq = (prev["seq"] + 1) if prev else 0
                        _latest[symbol] = {"best_bid": bids[0][0], "best_ask": asks[0][0], "seq": seq}
                        last_message_time[0] = time.time()
                        if not first_message_received[0]:
                            first_message_received[0] = True
                            logger.info(f"First ticker message received for {symbol} (bybit).")
                except Exception as e:
                    logger.error(f"Error handling ticker message for {symbol}: {e}")

            ws.orderbook_stream(depth=1, symbol=symbol, callback=handle_message)
            logger.info(f"WebSocket subscribed to orderbook stream for {symbol} (bybit).")

            while True:
                time.sleep(5)
                elapsed = time.time() - last_message_time[0]
                if elapsed > STALE_THRESHOLD:
                    logger.warning(
                        f"No ticker message from bybit for {symbol} in {elapsed:.0f}s. Reconnecting..."
                    )
                    break

        except Exception as e:
            logger.error(f"WebSocket error for {symbol}: {e}. Retrying in 1 second...")
            time.sleep(1)
        finally:
            if ws:
                try:
                    ws.exit()
                except Exception as close_err:
                    logger.warning(f"Error closing WebSocket for {symbol}: {close_err}")


def get_ticker(symbol: str):
    redis_key = f"ticker:bybit:{symbol}"
    ticker_raw = redis_conn.get(redis_key)
    if ticker_raw:
        ticker_data = json.loads(ticker_raw)
        return {
            "best_bid": ticker_data["best_bid"],
            "best_ask": ticker_data["best_ask"],
        }
    return None


def fetch_ticker_data(symbol: str):
    threading.Thread(target=subscribe_symbol_ticker, args=(symbol,), daemon=True).start()
