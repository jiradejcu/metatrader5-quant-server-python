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

def get_arbitrage_summary():
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
        netExpose = binance_size + (mt5_size * ratio) # 1 PAXG = 0.01 XAU
        netExposeAction = 'Safe'

        # handle floating point issue
        epsilon = 1e-12 
        if abs(netExpose) < epsilon:
            netExpose = 0

        if netExpose != 0:
            netExposeAction = 'Unsafe'

        if binance_size > 0:
            binance_action = 'LONG'
        elif binance_size == 0:
            binance_action = 'None'

        if mt5_size > 0:
            mt5_action = 'LONG'
        elif mt5_size == 0:
            mt5_action = 'None'

        if netExpose == 0:
            pairStatus = 'Complete'

        if redis_conn.get(pause_position_key):
            pause_position = 'Pause' 

        now = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S") # use UTC(+7) Thailand time zone
        response_data = {
            'binanceMarkPrice': float(result.get('markPrice', 0)),
            'mt5MarkPrice': float(mt5_result.get('markPrice', 0)),
            'binanceEntry': float(result.get('entryPrice', 0)),
            'mt5Entry': float(mt5_result.get('entryPrice',0)),
            'spread': float(result.get('markPrice', 0)) - float(mt5_result.get('markPrice', 0)),
            'pairStatus': pairStatus,
            'binanceSize': binance_size,
            'binanceAction': binance_action,
            'mt5Size': mt5_size,
            'netExpose': netExpose,
            'netExposeAction': netExposeAction,
            'mt5Action': mt5_action,
            'unrealizedBinance': sum(unrealizes),
            'pausePositionSync': pause_position,
            'time_update_mt5': now,
            'time_update_binance': now,
            'binanceSymbol': binance_symbol,
            'mt5Symbol': mt5_symbol,
        }

        return response_data
    except Exception as e:
        logging.error(f"Get arbitrage data error: {e}")