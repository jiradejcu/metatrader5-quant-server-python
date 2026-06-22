from utils.prepare_json import prepare_json
import time
from datetime import datetime, timedelta, timezone
import json
from utils.redis_client import get_redis_connection
from dotenv import load_dotenv
import os
import logging
from constants.config import PAIRS

load_dotenv()
PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
logger = logging.getLogger(__name__)

primary_data_default = {'positionAmt': 0, 'markPrice': 0, 'unRealizedProfit': 0, 'time_update': None, 'updateTime': None}
grid_data_default = {'long_upper_limit': 0.0, 'long_lower_limit': 0.0, 'short_upper_limit': 0.0, 'short_lower_limit': 0.0, 'max_position_size': 0.0, 'order_size': 0.0}

def get_grid_parameters_data():
        redis_conn = get_redis_connection()
        try:
                primary_exchange = PAIRS[PAIR_INDEX]['primary']['exchange']
                primary_symbol = PAIRS[PAIR_INDEX]['primary']['symbol']
                hedge_symbol = PAIRS[PAIR_INDEX]['hedge']['symbol']

                primary_key = f"position:{primary_exchange}:{primary_symbol}"
                grid_parameters_key = f"setting_grid_channel:{primary_symbol}:{hedge_symbol}"
                result = prepare_json(redis_conn.get(primary_key), primary_data_default)
                raw_grid_data = redis_conn.get(grid_parameters_key)
                if raw_grid_data is None:
                        return None

                grid_data = prepare_json(raw_grid_data, grid_data_default)

                ict_now = datetime.utcnow() + timedelta(hours=7)
                now = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S") # use UTC(+7) Thailand time zone

                data = {
                "long_upper_limit": float(grid_data.get('long_upper_limit', 0.0)),
                "long_lower_limit": float(grid_data.get('long_lower_limit', 0.0)),
                "short_upper_limit": float(grid_data.get('short_upper_limit', 0.0)),
                "short_lower_limit": float(grid_data.get('short_lower_limit', 0.0)),
                "max_position_size": float(grid_data.get('max_position_size', 0.0)),
                "order_size": float(grid_data.get('order_size', 0.0)),
                "mark_price": float(result.get('markPrice', 0.0)),

                "time": now
                }

                return data
        except Exception as e:
                logging.error(f"Get grid parameters data error: {e}")
