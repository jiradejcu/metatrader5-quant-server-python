import logging
import threading
import os
import time
import requests
from . import config
from decimal import Decimal
from app.utils.api.data import symbol_info_tick
from app.connectors.binance.api.ticker import get_ticker
from app.utils.redis_client import get_redis_connection
import json

WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')
logger = logging.getLogger(__name__)
redis_conn = get_redis_connection()
        
def compare():
    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    entry_symbol = config.PAIRS[PAIR_INDEX]['entry']['symbol']
    hedge_symbol = config.PAIRS[PAIR_INDEX]['hedge']['symbol']
    
    entry_ticker = get_ticker(entry_symbol)
    hedge_tick = symbol_info_tick(hedge_symbol)

    if entry_ticker is None:
        logger.warning(f"No entry ticker data for {entry_symbol} in Redis")
        return

    if hedge_tick is None or hedge_tick.empty:
        logger.warning(f"No hedge tick data for {hedge_symbol}")
        return

    try:
        entry_ask = Decimal(entry_ticker['best_ask'])
        entry_bid = Decimal(entry_ticker['best_bid'])

        hedge_ask = Decimal(str(hedge_tick.ask[0]))
        hedge_bid = Decimal(str(hedge_tick.bid[0]))
    except (KeyError, IndexError, AttributeError) as e:
        logger.error(f"Error parsing ticker data for {entry_symbol}/{hedge_symbol}: {e}")
        return

    percent_change_premium = None
    percent_change_discount = None

    try:
        percent_change_premium = (entry_ask - hedge_ask) / hedge_ask * Decimal('100')
        percent_change_discount = (entry_bid - hedge_bid) / hedge_bid * Decimal('100')
        
    except Exception as e:
        logger.exception(f"Error calculating percent change for {entry_symbol} and {hedge_symbol}: {e}")
        return

    result = {
        "entry_symbol": entry_symbol,
        "hedge_symbol": hedge_symbol,
        "percent_change_premium": str(percent_change_premium),
        "percent_change_discount": str(percent_change_discount)
    }
    
    logger.info(f"Price comparison for {entry_symbol} and {hedge_symbol}: {result}")
    
    try:
        redis_key = f"price_comparison:{entry_symbol}:{hedge_symbol}"
        redis_conn.set(redis_key, json.dumps(result))
        redis_conn.expire(redis_key, 10)
        
        redis_conn.publish(redis_key, json.dumps(result))
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
            logger.error(f"Error during price comparison: {e}", exc_info=True)
        time.sleep(1)

def start_comparison():
    if os.environ.get('RUN_MAIN') != 'true':
        return
    
    threading.Thread(target=comparison_loop, daemon=True).start()
