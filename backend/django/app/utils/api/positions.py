import os
import traceback
from typing import List, Dict
from datetime import datetime
import logging
import time

import requests
import pandas as pd
from dotenv import load_dotenv

from app.utils.constants import MT5Timeframe

logger = logging.getLogger(__name__)
load_dotenv()

BASE_URL = os.getenv('MT5_API_URL')

empty_df = pd.DataFrame(columns=[
    'ticket', 'time', 'time_msc', 'time_update', 'time_update_msc', 'type',
    'magic', 'identifier', 'reason', 'volume', 'price_open', 'sl', 'tp',
    'price_current', 'swap', 'profit', 'symbol', 'comment', 'external_id'
])

def get_positions() -> pd.DataFrame:
    try:
        url = f"{BASE_URL}/get_positions"
        start_time = time.time()  # Start timing
        response = requests.get(url, timeout=10)
        end_time = time.time()    # End timing
        duration = end_time - start_time
        logger.info(f"Fetched positions in {duration:.2f} seconds")

        response.raise_for_status()
        
        data = response.json()

        df = pd.DataFrame(data if isinstance(data, list) else [])

        if df.empty:
            return empty_df

        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
        df['time_update'] = pd.to_datetime(df['time_update'], unit='s', utc=True)

        return df
    
    except requests.exceptions.Timeout:
        error_msg = f"Timeout fetching positions from {url}"
        logger.error(error_msg)
        return empty_df
    
    except Exception as e:
        error_msg = f"Exception fetching positions: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)
        return empty_df

def get_position_by_symbol(symbol: str) -> Dict:
    positions_df = get_positions()
    position_row = positions_df[positions_df['symbol'] == symbol]

    if position_row.empty:
        return { 'volume': 0, 'profit': 0 }

    return position_row.iloc[0].to_dict()