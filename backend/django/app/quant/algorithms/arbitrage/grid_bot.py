import logging
import time
import threading
import os
from . import config
from decimal import Decimal


logger = logging.getLogger(__name__)

def handle_grid_flow():
    global latest_update
    
    try:
        PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
        binance_symbol = config.PAIRS[PAIR_INDEX]['binance']
        mt5_symbol = config.PAIRS[PAIR_INDEX]['mt5']
        logger.info(f"Starting grid trading process for {binance_symbol} ...")
        redis_conn = get_redis_connection()
        pubsub = redis_conn.pubsub()
        pubsub.subscribe(f"Setting Grid channel:{binance_symbol}:{mt5_symbol}")
        logger.info(f"Subscribed to Redis channel setting: {binance_symbol} for doing grid trading.")
    except Exception as e:
        logger.error(f"Error handle grid flow process because: {e}", exc_info=True)

# function running new thread
