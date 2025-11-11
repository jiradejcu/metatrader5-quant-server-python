import logging
import threading
import os
import time
from . import config
from decimal import Decimal
from app.utils.api.data import symbol_info_tick
from app.connectors.binance.api.ticker import get_ticker

logger = logging.getLogger(__name__)

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
        "percent_change_premium": percent_change_premium,
        "percent_change_discount": percent_change_discount
    }
    
    logger.info(f"Price comparison for {binance_symbol} and {mt5_symbol}: {result}")

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
