import logging
import time
import json
import threading
from pybit.unified_trading import WebSocket
from app.utils.redis_client import get_redis_connection

logger = logging.getLogger(__name__)
redis_conn = get_redis_connection()


STALE_THRESHOLD = 30  # seconds without a message before reconnecting


def subscribe_symbol_ticker(symbol: str):
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
                        best_bid = bids[0][0]
                        best_ask = asks[0][0]
                        redis_key = f"ticker:bybit:{symbol}"
                        payload = json.dumps({"best_bid": best_bid, "best_ask": best_ask})
                        redis_conn.set(redis_key, payload, ex=10)
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
