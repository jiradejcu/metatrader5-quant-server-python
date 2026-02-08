import logging
import time
import threading
import os
from . import config
from decimal import Decimal
import json
from app.utils.redis_client import get_redis_connection

logger = logging.getLogger(__name__)

# For securing uses global from many threads
data_lock = threading.Lock()
latest_update = None
latest_grid_settings = None
latest_price_diff = None

def handle_grid_flow(pubsub, price_diff_key, grid_range_key):
    global latest_update, latest_grid_settings, latest_price_diff
    logger.debug('Grid bot is runing!!')

    try:
        for message in pubsub.listen():
            # print(message)
            if message['type'] == 'subscribe':
                logger.info(f"Successfully subscribed to {message['channel'].decode('utf-8')}")
                continue

            if message['type'] == 'message':
                logger.info('Grid bot message still working!!')
                channel = message['channel'].decode('utf-8')
                data_payload = message['data']

                with data_lock:
                    # Update latest values from subscribe
                    if channel == price_diff_key:
                        price_dict = json.loads(data_payload) if data_payload else {}

                        latest_price_diff = round(
                            float(price_dict.get('percent_change_premium', "0")),
                            2
                        )
                    
                    if channel == grid_range_key:
                        grid_dict = json.loads(data_payload) if data_payload else {}

                        upper_diff = float(grid_dict.get('upper_diff', 0))
                        lower_diff = float(grid_dict.get('lower_diff', 0))

                        latest_grid_settings = {
                            "upper": upper_diff,
                            "lower": lower_diff
                        }

                    if latest_grid_settings is not None and latest_price_diff is not None:
                        print('check point!!')
                        print(latest_grid_settings)
                        print(latest_price_diff)
    except Exception as e:
        logger.error(f"Error handle grid flow process because: {e}", exc_info=True)

# function running new thread
def start_grid_bot_sync():

    try:
        PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
        binance_symbol = config.PAIRS[PAIR_INDEX]['binance']
        mt5_symbol = config.PAIRS[PAIR_INDEX]['mt5']
        logger.info(f"Starting grid trading process for {binance_symbol} ...")

        redis_conn = get_redis_connection()
        pubsub = redis_conn.pubsub()

        price_diff = f"price_comparison:{binance_symbol}:{mt5_symbol}"
        grid_range = f"Setting Grid channel:{binance_symbol}:{mt5_symbol}"
        pubsub.subscribe(price_diff, grid_range)

        threading.Thread(
            target=handle_grid_flow,
            args=(pubsub, price_diff, grid_range), daemon=True
        ).start()
        logger.info("Grid Bot thread started and running in background.")
    except Exception as e:
        logger.error(f"Error while syncing grid montinor: {e}", exc_info=True)

