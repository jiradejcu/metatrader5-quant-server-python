import time
from datetime import datetime, timedelta, timezone
import json
from utils.redis_client import get_redis_connection
from dotenv import load_dotenv
import os
import logging
from constants.config import PAIRS
from utils.prepare_json import prepare_json

load_dotenv()
PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
RATIO_EXPOSE= int(os.getenv('CONTRACT_SIZE'))
logger = logging.getLogger(__name__)

position_data_default = {'positionAmt': 0, 'markPrice': 0, 'unRealizedProfit': 0, 'time_update': None, 'updateTime': None}
latest_response_data = {}

def get_arbitrage_summary():
    global latest_response_data
    redis_conn = get_redis_connection()
    try:
        entry_symbol = PAIRS[PAIR_INDEX]['entry']['symbol']
        hedge_symbol = PAIRS[PAIR_INDEX]['hedge']['symbol']
        ratio = RATIO_EXPOSE

        entry_key = f"position:{entry_symbol}"
        hedge_key = f"position:{hedge_symbol}"
        pause_position_key = "position_sync_paused_flag"
        grid_bot_pause_key = "grid_bot_paused_flag"

        redis_conn = get_redis_connection()

        entry_result = prepare_json(redis_conn.get(entry_key), position_data_default)
        logger.info(f"Get redis key: position:{entry_symbol} success")
        hedge_result = prepare_json(redis_conn.get(hedge_key), position_data_default)
        logger.info(f"Get redis key: position:{hedge_symbol} success")
        price_diff = prepare_json(redis_conn.get(f"price_comparison:{entry_symbol}:{hedge_symbol}"), {})

        place_order_key = f"place order of {entry_symbol}"
        place_order_data = prepare_json(redis_conn.get(place_order_key), {})

        pause_position = 'Active'
        grid_bot_status = 'Active'
        pairStatus = 'Warning'

        entry_size = float(entry_result.get('positionAmt', 0))
        hedge_size = float(hedge_result.get('positionAmt', 0))
        unrealizes = [float(entry_result.get('unRealizedProfit', 0)), float(hedge_result.get('unRealizedProfit', 0))]

        if redis_conn.get(pause_position_key):
            pause_position = 'Pause'

        if redis_conn.get(grid_bot_pause_key):
            grid_bot_status = 'Pause'

        now = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S") # use UTC(+7) Thailand time zone
        response_data = {
            'entryMarkPrice': float(entry_result.get('markPrice', 0)),
            'hedgeMarkPrice': float(hedge_result.get('markPrice', 0)),
            'entryPrice': float(entry_result.get('entryPrice', 0)),
            'hedgePrice': float(hedge_result.get('entryPrice', 0)),
            'entrySize': entry_size,
            'hedgeSize': hedge_size,
            'pausePositionSync': pause_position,
            'gridBotStatus': grid_bot_status,
            'time_update_hedge': now,
            'time_update_entry': now,
            'entrySymbol': entry_symbol,
            'hedgeSymbol': hedge_symbol,
            'entry_unrealized_profit': float(entry_result.get('unRealizedProfit', 0)),
            'hedge_unrealized_profit': float(hedge_result.get('unRealizedProfit', 0)),
            'price_diff_percent': round(float(price_diff.get('percent_change_premium', "0")), 3),
            'current_upper_diff': place_order_data.get('current_upper_diff', None),
            'current_lower_diff': place_order_data.get('current_lower_diff', None),
        }

        response_data['netExpose'] = response_data['entrySize'] + (response_data['hedgeSize'] * ratio)
        response_data['spread'] = response_data['entryMarkPrice'] - response_data['hedgeMarkPrice']
        response_data['unrealizedTotal'] = response_data['entry_unrealized_profit'] + response_data['hedge_unrealized_profit']
        response_data['netExposeAction'] = 'Safe'

        # handle floating point issue
        epsilon = 1e-12
        if abs(response_data['netExpose']) < epsilon:
            response_data['netExpose'] = 0

        if response_data['netExpose'] != 0:
            response_data['netExposeAction'] = 'Unsafe'

        if response_data['entrySize'] > 0:
            response_data['entryAction'] = 'LONG'
        elif response_data['entrySize'] == 0:
            response_data['entryAction'] = 'None'
        else:
            response_data['entryAction'] = 'SHORT'

        if response_data['hedgeSize'] > 0:
            response_data['hedgeAction'] = 'LONG'
        elif response_data['hedgeSize'] == 0:
            response_data['hedgeAction'] = 'None'
        else:
            response_data['hedgeAction'] = 'SHORT'

        if response_data['netExpose'] == 0:
            response_data['pairStatus'] = 'Complete'

        return response_data
    except Exception as e:
        logging.error(f"Get arbitrage data error: {e}")
