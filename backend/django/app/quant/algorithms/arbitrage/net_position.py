import time
import os
import logging
import threading
from . import config
from app.utils.api.positions import get_position_list_by_symbol
from app.utils.api.order import close_by

logger = logging.getLogger(__name__)

def check_position_loop():
    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    mt5_symbol = config.PAIRS[PAIR_INDEX]['mt5']
    
    while True:
        try:
            positions = get_position_list_by_symbol(mt5_symbol)
            if positions:
                logger.info(f"Checking for opposite positions for {mt5_symbol}. Total: {len(positions)}")
                
                # Group positions by type
                buys = [p for p in positions if p['type'] == 0]   # 0 = POSITION_TYPE_BUY
                sells = [p for p in positions if p['type'] == 1]  # 1 = POSITION_TYPE_SELL
                
                # Execute CloseBy for pairs
                while buys and sells:
                    buy_pos = buys.pop(0)
                    sell_pos = sells.pop(0)
                    
                    buy_ticket = buy_pos['ticket']
                    sell_ticket = sell_pos['ticket']
                    
                    logger.info(f"Executing CloseBy for {mt5_symbol}: BUY #{buy_ticket} and SELL #{sell_ticket}")
                    result = close_by(mt5_symbol, buy_ticket, sell_ticket)
                    
                    if result:
                        logger.info(f"CloseBy order successful for tickets {buy_ticket} and {sell_ticket}")
                    else:
                        logger.error(f"CloseBy order failed for tickets {buy_ticket} and {sell_ticket}")
            
        except Exception as e:
            logger.error(f"Error during position check: {e}", exc_info=True)
        time.sleep(1)

def start_net_position_check():
    if os.environ.get('RUN_MAIN') != 'true':
        return
    
    threading.Thread(target=check_position_loop, daemon=True).start()