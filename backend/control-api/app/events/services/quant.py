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
logger = logging.getLogger(__name__)

position_data_default = {'positionAmt': 0, 'markPrice': 0, 'unRealizedProfit': 0, 'time_update': None, 'updateTime': None}
latest_response_data = {}

def get_arbitrage_summary():
    global latest_response_data
    redis_conn = get_redis_connection()
    try:
        primary_exchange = PAIRS[PAIR_INDEX]['primary']['exchange']
        hedge_exchange = PAIRS[PAIR_INDEX]['hedge']['exchange']
        primary_symbol = PAIRS[PAIR_INDEX]['primary']['symbol']
        hedge_symbol = PAIRS[PAIR_INDEX]['hedge']['symbol']
        ratio = PAIRS[PAIR_INDEX]['contract_size']

        primary_key = f"position:{primary_exchange}:{primary_symbol}"
        hedge_key = f"position:{hedge_exchange}:{hedge_symbol}"
        pause_position_key = "position_sync_paused_flag"
        grid_bot_active_key = "grid_bot_active_flag"

        redis_conn = get_redis_connection()

        primary_result = prepare_json(redis_conn.get(primary_key), position_data_default)
        logger.info(f"Get redis key: {primary_key} success")
        hedge_result = prepare_json(redis_conn.get(hedge_key), position_data_default)
        logger.info(f"Get redis key: {hedge_key} success")
        price_diff_data = prepare_json(redis_conn.get(f"price_diff:{primary_symbol}:{hedge_symbol}"), {})

        pause_position = 'Active'
        grid_bot_status = 'Inactive'
        pairStatus = 'Warning'

        primary_size = float(primary_result.get('positionAmt', 0))
        hedge_size = float(hedge_result.get('positionAmt', 0))
        unrealizes = [float(primary_result.get('unRealizedProfit', 0)), float(hedge_result.get('unRealizedProfit', 0))]

        if redis_conn.get(pause_position_key):
            pause_position = 'Pause'

        if redis_conn.get(grid_bot_active_key):
            grid_bot_status = 'Active'

        now = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S") # use UTC(+7) Thailand time zone
        primary_mark_price = float(primary_result.get('markPrice', 0))
        hedge_mark_price = float(hedge_result.get('markPrice', 0))

        if primary_mark_price == 0.0:
            logger.warning(f"primaryMarkPrice is 0. primary_key={primary_key} primary_result={primary_result}")
        if hedge_mark_price == 0.0:
            logger.warning(f"hedgeMarkPrice is 0. hedge_key={hedge_key} hedge_result={hedge_result}")

        # hedgePrice  — group VWAP, unchanged by partial closes (mirrors Binance's entryPrice)
        # hedgeCurrentEntryPrice — live VWAP of only the remaining open MT5 lots
        hedge_group_entry = float(hedge_result.get('entryPrice', 0))
        hedge_current_entry = float(hedge_result.get('currentEntryPrice', hedge_result.get('entryPrice', 0)))
        hedge_group_id = hedge_result.get('groupId')

        response_data = {
            'primaryMarkPrice': primary_mark_price,
            'hedgeMarkPrice': hedge_mark_price,
            'primaryPrice': float(primary_result.get('entryPrice', 0)),
            'hedgePrice': hedge_group_entry,
            'hedgeCurrentEntryPrice': hedge_current_entry,
            'hedgeGroupId': hedge_group_id,
            'primarySize': primary_size,
            'hedgeSize': hedge_size,
            'pausePositionSync': pause_position,
            'gridBotStatus': grid_bot_status,
            'time_update_hedge': now,
            'time_update_primary': now,
            'primarySymbol': primary_symbol,
            'hedgeSymbol': hedge_symbol,
            'primary_unrealized_profit': float(primary_result.get('unRealizedProfit', 0)),
            'hedge_unrealized_profit': float(hedge_result.get('unRealizedProfit', 0)),
            'price_diff_percent': round(float(price_diff_data.get('ask_diff_percent', "0")), 3),
            'ask_diff': price_diff_data.get('ask_diff', None),
            'bid_diff': price_diff_data.get('bid_diff', None),
        }

        response_data['netExpose'] = response_data['primarySize'] + (response_data['hedgeSize'] * ratio)
        response_data['spread'] = response_data['primaryMarkPrice'] - response_data['hedgeMarkPrice']
        response_data['unrealizedTotal'] = response_data['primary_unrealized_profit'] + response_data['hedge_unrealized_profit']
        response_data['netExposeAction'] = 'Safe'

        # handle floating point issue
        epsilon = 1e-12
        if abs(response_data['netExpose']) < epsilon:
            response_data['netExpose'] = 0

        if response_data['netExpose'] != 0:
            response_data['netExposeAction'] = 'Unsafe'

        if response_data['primarySize'] > 0:
            response_data['primaryAction'] = 'LONG'
        elif response_data['primarySize'] == 0:
            response_data['primaryAction'] = 'None'
        else:
            response_data['primaryAction'] = 'SHORT'

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
