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
    binance_symbol = config.PAIRS[0]['binance']
    mt5_symbol = config.PAIRS[0]['mt5']
    
    binance_ticker = get_ticker(binance_symbol)
    mt5_tick = symbol_info_tick(mt5_symbol)
    
    binance_ask = Decimal(binance_ticker['best_ask'])
    binance_bid = Decimal(binance_ticker['best_bid'])
    
    mt5_ask = Decimal(str(mt5_tick.ask[0]))
    mt5_bid = Decimal(str(mt5_tick.bid[0]))
    
    percent_change_premium = None
    percent_change_discount = None
    
    try:
        percent_change_premium = (binance_ask - mt5_ask) / mt5_ask * Decimal('100')
        percent_change_discount = (binance_bid - mt5_bid) / mt5_bid * Decimal('100')
        
    except Exception as e:
        logger.exception(f"Error calculating percent change for {binance_symbol} and {mt5_symbol}: {e}")
        return

    result = {
        "binance_symbol": binance_symbol,
        "mt5_symbol": mt5_symbol,
        "percent_change_premium": str(percent_change_premium),
        "percent_change_discount": str(percent_change_discount)
    }
    
    logger.info(f"Price comparison for {binance_symbol} and {mt5_symbol}: {result}")
    
    try:
        redis_key = f"price_comparison:{binance_symbol}:{mt5_symbol}"
        redis_conn.set(redis_key, json.dumps(result))
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
            logger.error(f"Error during price comparison: {e}", exc_info=True)
        time.sleep(1)

def start_comparison():
    if os.environ.get('RUN_MAIN') != 'true':
        return
    
    threading.Thread(target=comparison_loop, daemon=True).start()
