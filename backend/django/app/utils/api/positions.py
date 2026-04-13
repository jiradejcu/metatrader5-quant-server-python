import os
import asyncio
import traceback
import json
from typing import List, Dict
from datetime import datetime
import logging
import time
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd
import numpy as np
from decimal import Decimal
from dotenv import load_dotenv
from app.utils.redis_client import get_redis_connection

from app.utils.constants import MT5Timeframe

logger = logging.getLogger(__name__)
load_dotenv()

BASE_URL = os.getenv('MT5_API_URL')
TZ = timezone(timedelta(hours=7))

empty_df = pd.DataFrame(columns=[
    'ticket', 'time', 'time_msc', 'time_update', 'time_update_msc', 'type',
    'magic', 'identifier', 'reason', 'volume', 'price_open', 'sl', 'tp',
    'price_current', 'swap', 'profit', 'symbol', 'comment', 'external_id'
])

def _add_signed_volume(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['signed_volume'] = df['volume'] * df['type'].apply(lambda x: -1 if x == 1 else 1)
    return df

def get_positions() -> pd.DataFrame:
    try:
        url = f"{BASE_URL}/get_positions"
        response = requests.get(url, timeout=10)
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
    redis_conn = get_redis_connection()
    cached = redis_conn.get(f"position:mt5:{symbol}")
    if cached:
        data = json.loads(cached)
        return {
            'volume': data.get('positionAmt', '0'),
            'time_update': data.get('time_update'),
            'entryPrice': data.get('entryPrice', '0'),
            'unRealizedProfit': data.get('unRealizedProfit', '0'),
        }

    positions_df = get_positions()
    symbol_positions = positions_df[positions_df['symbol'] == symbol]
    latest_update = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

    if symbol_positions.empty:
        return {
            'volume': Decimal(0),
            'time_update': latest_update,
            'entryPrice': Decimal(0),
            'unRealizedProfit': Decimal(0),
        }

    symbol_positions = _add_signed_volume(symbol_positions)
    net_volume = symbol_positions['signed_volume'].sum()
    return {
        'volume': net_volume,
        'time_update': latest_update,
        'entryPrice': positions_df['price_open'].iloc[0],
        'unRealizedProfit': positions_df['profit'].sum(),
    }

def get_position_list_by_symbol(symbol: str) -> List[Dict]:
    positions_df = get_positions()
    symbol_positions = positions_df[positions_df['symbol'] == symbol]
    return symbol_positions.to_dict('records')

async def subscribe_hedge_position(symbol: str):
    logger.info(f"Starting MT5 hedge position subscription for {symbol}.")
    redis_conn = get_redis_connection()
    while True:
        try:
            positions = get_positions()
            positions = positions[positions['symbol'] == symbol]
            redis_key = f"position:mt5:{symbol}"

            if redis_conn.exists(redis_key):
                redis_conn.delete(redis_key)

            now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
            result = {
                "time_update": now,
                "entryPrice": "0",
                "markPrice": "0",
                "unRealizedProfit": "0",
                "positionAmt": "0"
            }

            ticker_hedge_key = f"ticker:mt5:{symbol}"
            ticker_hedge_raw = redis_conn.get(ticker_hedge_key)
            ticker_hedge = json.loads(ticker_hedge_raw) if ticker_hedge_raw else {}
            bid = float(ticker_hedge.get('best_bid') or 0.0)
            ask = float(ticker_hedge.get('best_ask') or 0.0)
            result["markPrice"] = ask

            if not positions.empty:
                positions = _add_signed_volume(positions)

                total_volume = float(positions['signed_volume'].sum())
                weighted_entry = float((positions['price_open'] * positions['signed_volume']).sum() / positions['signed_volume'].sum()) if total_volume != 0.0 else 0
                total_profit = 0 if total_volume == 0.0 else float(positions['profit'].sum())
                mark_price = float(ask if total_volume < 0 else bid)

                result["entryPrice"] = f"{weighted_entry:.3f}"
                result["markPrice"] = f"{mark_price:.3f}"
                result["unRealizedProfit"] = f"{total_profit:.2f}"
                result["positionAmt"] = f"{total_volume:.3f}"

            data = json.dumps(result)
            redis_conn.set(redis_key, data)
            redis_conn.publish(redis_key, data)
            redis_conn.expire(redis_key, 10)

            await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.error(f"Hedge position subscription for {symbol} cancelled.")
            break
        except Exception as e:
            logger.error(f"Hedge position subscription error for {symbol}: {e}. Retrying in 1 second...")
            await asyncio.sleep(1)