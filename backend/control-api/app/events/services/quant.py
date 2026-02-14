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
        binance_symbol = PAIRS[PAIR_INDEX]['binance']
        mt5_symbol = PAIRS[PAIR_INDEX]['mt5']
        ratio = RATIO_EXPOSE

        binance_key = f"position:{binance_symbol}"
        mt5_key = f"position: {mt5_symbol}"
        pause_position_key = "position_sync_paused_flag"

        redis_conn = get_redis_connection()

        result = prepare_json(redis_conn.get(binance_key), position_data_default)
        logger.info(f"Get redis key: position: {binance_symbol} success")
        mt5_result = prepare_json(redis_conn.get(mt5_key), position_data_default)
        logger.info(f"Get redis key: position: {mt5_symbol} success")
        
        pause_position = 'Active'
        binance_action = 'SHORT'
        mt5_action = 'SHORT'
        pairStatus = 'Warning'

        binance_size = float(result.get('positionAmt', 0))
        mt5_size = float(mt5_result.get('positionAmt', 0))
        unrealizes = [float(result.get('unRealizedProfit', 0)), float(mt5_result.get('unRealizedProfit', 0))]
        

        if redis_conn.get(pause_position_key):
            pause_position = 'Pause' 

        now = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S") # use UTC(+7) Thailand time zone
        response_data = {
            'binanceMarkPrice': float(result.get('markPrice', 0)),
            'mt5MarkPrice': float(mt5_result.get('markPrice', 0)),
            'binanceEntry': float(result.get('entryPrice', 0)),
            'mt5Entry': float(mt5_result.get('entryPrice',0)),
            'binanceSize': binance_size,
            'mt5Size': mt5_size,
            'pausePositionSync': pause_position,
            'time_update_mt5': now,
            'time_update_binance': now,
            'binanceSymbol': binance_symbol,
            'mt5Symbol': mt5_symbol,
            'binance_unrealized_profit': float(result.get('unRealizedProfit', 0)),
            'mt5_unrealized_profit': float(mt5_result.get('unRealizedProfit', 0))
        }

        # Fill missing data from the latest response (Clean data)
        if latest_response_data != {} and response_data['binanceMarkPrice'] == 0 and latest_response_data['binanceMarkPrice'] != 0:
            response_data['binanceMarkPrice'] = latest_response_data['binanceMarkPrice']
        if latest_response_data != {} and response_data['mt5MarkPrice'] == 0 and latest_response_data['mt5MarkPrice'] != 0:
            response_data['mt5MarkPrice'] = latest_response_data['mt5MarkPrice']
        if latest_response_data != {} and response_data['binanceEntry'] == 0 and latest_response_data['binanceEntry'] != 0:
            response_data['binanceEntry'] = latest_response_data['binanceEntry']
        if latest_response_data != {} and response_data['mt5Entry'] == 0 and latest_response_data['mt5Entry'] != 0:
            response_data['mt5Entry'] = latest_response_data['mt5Entry']
        if latest_response_data != {} and response_data['binanceSize'] == 0 and latest_response_data['binanceSize'] != 0:
            response_data['binanceSize'] = latest_response_data['binanceSize']
        if latest_response_data != {} and response_data['mt5Size'] == 0 and latest_response_data['mt5Size'] != 0:
            response_data['mt5Size'] = latest_response_data['mt5Size']
        if latest_response_data != {} and response_data['binance_unrealized_profit'] == 0 and latest_response_data['unrealizedBinance'] != 0:
            response_data['binance_unrealized_profit'] = latest_response_data['binance_unrealized_profit']
        if latest_response_data != {} and response_data['mt5_unrealized_profit'] == 0 and latest_response_data['mt5_unrealized_profit'] != 0:
            response_data['mt5_unrealized_profit'] = latest_response_data['mt5_unrealized_profit']

        response_data['netExpose'] = response_data['binanceSize'] + (response_data['mt5Size'] * ratio) # 1 PAXG = 0.01 XAU
        response_data['spread'] = response_data['binanceMarkPrice'] - response_data['mt5MarkPrice']
        response_data['unrealizedBinance'] = response_data['binance_unrealized_profit'] + response_data['mt5_unrealized_profit']
        response_data['netExposeAction'] = 'Safe'

        # handle floating point issue
        epsilon = 1e-12 
        if abs(response_data['netExpose']) < epsilon:
            response_data['netExpose'] = 0

        if response_data['netExpose'] != 0:
            response_data['netExposeAction'] = 'Unsafe'

        if response_data['binanceSize'] > 0:
            response_data['binanceAction'] = 'LONG'
        elif response_data['binanceSize'] == 0:
            response_data['binanceAction'] = 'None'
        else:
            response_data['binanceAction'] = 'SHORT'

        if response_data['mt5Size'] > 0:
            response_data['mt5Action'] = 'LONG'
        elif response_data['mt5Size'] == 0:
            response_data['mt5Action'] = 'None'
        else:
            response_data['mt5Action'] = 'SHORT'

        if response_data['netExpose'] == 0:
            response_data['pairStatus'] = 'Complete'    
        
        # Update the latest response data for future reference
        latest_response_data = response_data

        return response_data
    except Exception as e:
        logging.error(f"Get arbitrage data error: {e}")