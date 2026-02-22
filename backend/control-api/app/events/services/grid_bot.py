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

binance_data_default = {'positionAmt': 0, 'markPrice': 0, 'unRealizedProfit': 0, 'time_update': None, 'updateTime': None}
grid_data_default = {'upper_diff': 0.0, 'lower_diff': 0.0, 'max_position_size': 0.0, 'order_size': 0.0, 'close_long': 0.0, 'close_short': 0.0 } 

def get_grid_parameters_data():
        redis_conn = get_redis_connection()
        try:
                binance_symbol = PAIRS[PAIR_INDEX]['binance']
                mt5_symbol = PAIRS[PAIR_INDEX]['mt5']

                binance_key = f"position:{binance_symbol}"
                grid_parameters_key = f"setting_grid_channel:{binance_symbol}:{mt5_symbol}"
                result = prepare_json(redis_conn.get(binance_key), binance_data_default)
                grid_data = prepare_json(redis_conn.get(grid_parameters_key), grid_data_default)

                ict_now = datetime.utcnow() + timedelta(hours=7)
                now = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S") # use UTC(+7) Thailand time zone

                data = {
                "upper_diff": float(grid_data.get('upper_diff', 0.0)),
                "lower_diff": float(grid_data.get('lower_diff', 0.0)),
                "max_position_size": float(grid_data.get('max_position_size', 0.0)),
                "order_size": float(grid_data.get('order_size', 0.0)),
                "mark_price": float(result.get('markPrice', 0.0)),
                "close_long": float(grid_data.get('close_long', 0.0)),
                "close_short": float(grid_data.get('close_short', 0.0)),
                "time": now
                }

                return data
        except Exception as e:
                logging.error(f"Get grid parameters data error: {e}")