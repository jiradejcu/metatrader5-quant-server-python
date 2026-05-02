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
logger = logging.getLogger(__name__)
redis_conn = get_redis_connection()


def compare():
    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    entry_exchange = config.PAIRS[PAIR_INDEX]['entry']['exchange']
    entry_symbol = config.PAIRS[PAIR_INDEX]['entry']['symbol']
    hedge_symbol = config.PAIRS[PAIR_INDEX]['hedge']['symbol']

    get_ticker = _get_ticker_fn(entry_exchange)
    entry_ticker = get_ticker(entry_symbol)

    ticker_mt5_raw = redis_conn.get(f"ticker:mt5:{hedge_symbol}")
    hedge_ticker = json.loads(ticker_mt5_raw) if ticker_mt5_raw else None

    if entry_ticker is None:
        logger.warning(f"No entry ticker data for {entry_symbol} in Redis")
        return

    if hedge_ticker is None:
        logger.warning(f"No hedge ticker data for {hedge_symbol} in Redis")
        return

    try:
        entry_ask = Decimal(entry_ticker['best_ask'])
        entry_bid = Decimal(entry_ticker['best_bid'])

        hedge_ask = Decimal(str(hedge_ticker.get('best_ask', 0)))
        hedge_bid = Decimal(str(hedge_ticker.get('best_bid', 0)))
    except (KeyError, IndexError, AttributeError) as e:
        logger.error(f"Error parsing ticker data for {entry_symbol}/{hedge_symbol}: {e}")
        return

    try:
        ask_diff = round(float(entry_ask - hedge_ask), 2)
        bid_diff = round(float(entry_bid - hedge_bid), 2)
        ask_diff_percent = (entry_ask - hedge_ask) / hedge_ask * Decimal('100')
        bid_diff_percent = (entry_bid - hedge_bid) / hedge_bid * Decimal('100')
    except Exception as e:
        logger.exception(f"Error calculating price diff for {entry_symbol} and {hedge_symbol}: {e}")
        return

    result = {
        "entry_symbol": entry_symbol,
        "hedge_symbol": hedge_symbol,
        "ask_diff": ask_diff,
        "bid_diff": bid_diff,
        "ask_diff_percent": str(ask_diff_percent),
        "bid_diff_percent": str(bid_diff_percent),
    }

    logger.info(f"Price diff for {entry_symbol}/{hedge_symbol}: {result}")

    try:
        redis_key = f"price_diff:{entry_symbol}:{hedge_symbol}"
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
