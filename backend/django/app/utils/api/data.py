import os
import json
import time
import asyncio
import requests
import traceback
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
import logging

from app.utils.constants import MT5Timeframe
from app.utils.redis_client import get_redis_connection

load_dotenv()
logger = logging.getLogger(__name__)
redis_conn = get_redis_connection()

BASE_URL = os.getenv('MT5_API_URL')

def symbol_info_tick(symbol: str) -> pd.DataFrame:
    try:
        url = f"{BASE_URL}/symbol_info_tick/{symbol}"
        response = requests.get(url)
        response.raise_for_status()
        
        data = response.json()
        # Wrap the data in a list to create a single-row DataFrame
        df = pd.DataFrame([data])
        return df
    except Exception as e:
        error_msg = f"Exception fetching symbol info tick for {symbol}: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)

def symbol_info(symbol) -> pd.DataFrame:
    try:
        url = f"{BASE_URL}/symbol_info/{symbol}"
        response = requests.get(url)
        response.raise_for_status()
        
        data = response.json()
        df = pd.DataFrame([data])
        return df
    except Exception as e:
        error_msg = f"Exception fetching symbol info for {symbol}: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)

def fetch_data_pos(symbol: str, timeframe: MT5Timeframe, bars: int) -> pd.DataFrame:
    try:
        url = f"{BASE_URL}/fetch_data_pos?symbol={symbol}&timeframe={timeframe.value}&bars={bars}"
        response = requests.get(url)
        response.raise_for_status()
        
        data = response.json()
        df = pd.DataFrame(data)
        return df
    except Exception as e:
        error_msg = f"Exception fetching data for {symbol} on {timeframe}: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)

def fetch_data_range(symbol: str, timeframe: MT5Timeframe, from_date: datetime, to_date: datetime) -> pd.DataFrame:
    try:
        url = f"{BASE_URL}/copy_rates_range"
        params = {
            'symbol': symbol,
            'timeframe': timeframe.value,
            'from_date': from_date,
            'to_date': to_date
        }
        response = requests.post(url, params=params)
        response.raise_for_status()

        data = response.json()
        df = pd.DataFrame(data)
        return df
    except Exception as e:
        error_msg = f"Exception fetching data for {symbol} on {timeframe}: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)


def subscribe_symbol_ticker(symbol: str):
    while True:
        tick = symbol_info_tick(symbol)

        if tick is not None and not tick.empty:
            try:
                ask = float(tick['ask'].iloc[0]) if 'ask' in tick else 0
                bid = float(tick['bid'].iloc[0]) if 'bid' in tick else 0

                ticker_key = f"ticker (MT5):{symbol}"
                redis_conn.set(ticker_key, json.dumps({"best_ask": ask, "best_bid": bid}))
                redis_conn.publish(ticker_key, json.dumps({"best_ask": ask, "best_bid": bid}))
                redis_conn.expire(ticker_key, 10)
                time.sleep(0.1)
            except asyncio.CancelledError:
                logger.error(f"MT5 ticker task for {symbol} cancelled.")
                break
            except Exception as e:
                logger.error(f"MT5 ticker task error for {symbol}: {e}. Retrying in 1 second...")
                time.sleep(1)
