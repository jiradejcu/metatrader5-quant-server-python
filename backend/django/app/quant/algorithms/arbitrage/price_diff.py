import logging
import threading
import importlib
import os
import time
import requests
from . import config
from decimal import Decimal
from app.utils.redis_client import get_redis_connection
import json


def _get_ticker_fn(exchange: str):
    module = importlib.import_module(f"app.connectors.{exchange}.api.ticker")
    return module.get_ticker

WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')
PRICE_DIFF_MAX_AGE_MS = int(os.getenv('PRICE_DIFF_MAX_AGE_MS', '1600'))
logger = logging.getLogger(__name__)
redis_conn = get_redis_connection()


def compare():
    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    primary_exchange = config.PAIRS[PAIR_INDEX]['primary']['exchange']
    primary_symbol = config.PAIRS[PAIR_INDEX]['primary']['symbol']
    hedge_symbol = config.PAIRS[PAIR_INDEX]['hedge']['symbol']

    now_ms = time.time() * 1000

    get_ticker = _get_ticker_fn(primary_exchange)
    primary_ticker = get_ticker(primary_symbol)

    ticker_mt5_raw = redis_conn.get(f"ticker:mt5:{hedge_symbol}")
    hedge_ticker = json.loads(ticker_mt5_raw) if ticker_mt5_raw else None

    if primary_ticker is None:
        logger.warning(f"No primary ticker data for {primary_symbol} in Redis")
        return

    if hedge_ticker is None:
        logger.warning(f"No hedge ticker data for {hedge_symbol} in Redis")
        return

    primary_price_age_ms = now_ms - primary_ticker.get("event_ts", 0)
    if primary_price_age_ms > PRICE_DIFF_MAX_AGE_MS:
        logger.warning(f"Stale primary ticker for {primary_symbol}: {primary_price_age_ms:.0f}ms old — skipping")
        return

    hedge_price_age_ms = now_ms - hedge_ticker.get("event_ts", 0)
    if hedge_price_age_ms > PRICE_DIFF_MAX_AGE_MS:
        logger.warning(f"Stale hedge ticker for {hedge_symbol}: {hedge_price_age_ms:.0f}ms old — skipping")
        return

    try:
        primary_ask = Decimal(primary_ticker['best_ask'])
        primary_bid = Decimal(primary_ticker['best_bid'])

        hedge_ask = Decimal(str(hedge_ticker.get('best_ask', 0)))
        hedge_bid = Decimal(str(hedge_ticker.get('best_bid', 0)))
    except (KeyError, IndexError, AttributeError) as e:
        logger.error(f"Error parsing ticker data for {primary_symbol}/{hedge_symbol}: {e}")
        return

    try:
        ask_diff = round(float(primary_ask - hedge_ask), 2)
        bid_diff = round(float(primary_bid - hedge_bid), 2)
        ask_diff_percent = (primary_ask - hedge_ask) / hedge_ask * Decimal('100')
        bid_diff_percent = (primary_bid - hedge_bid) / hedge_bid * Decimal('100')
    except Exception as e:
        logger.exception(f"Error calculating price diff for {primary_symbol} and {hedge_symbol}: {e}")
        return

    result = {
        "primary_symbol": primary_symbol,
        "hedge_symbol": hedge_symbol,
        "ask_diff": ask_diff,
        "bid_diff": bid_diff,
        "ask_diff_percent": f"{ask_diff_percent:.3f}",
        "bid_diff_percent": f"{bid_diff_percent:.3f}",
        "primary_ask": float(primary_ask),
        "hedge_ask": float(hedge_ask),
        "primary_bid": float(primary_bid),
        "hedge_bid": float(hedge_bid),
        "ts": min(primary_ticker["event_ts"], hedge_ticker.get("event_ts", primary_ticker["event_ts"])),
    }

    logger.debug(f"Price diff for {primary_symbol}/{hedge_symbol}: {result}")

    try:
        redis_key = f"price_diff:{primary_symbol}:{hedge_symbol}"
        redis_conn.set(redis_key, json.dumps(result))
        redis_conn.publish(redis_key, json.dumps(result))
        redis_conn.expire(redis_key, 10)
    except Exception as e:
        logger.error(f"Error sending result to Redis: {e}", exc_info=True)

    if WEBHOOK_URL:
        try:
            response = requests.post(WEBHOOK_URL, json=result, timeout=1)
            response.raise_for_status()
            logger.info(f"Successfully sent result to N8N webhook: {response.status_code}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending result to N8N webhook: {e}", exc_info=True)

def comparison_loop():
    while True:
        try:
            compare()
        except Exception as e:
            logger.error(f"Error during price diff comparison: {e}", exc_info=True)
        time.sleep(0.2)

def start_comparison():
    if os.environ.get('RUN_MAIN') != 'true':
        return

    threading.Thread(target=comparison_loop, daemon=True).start()
