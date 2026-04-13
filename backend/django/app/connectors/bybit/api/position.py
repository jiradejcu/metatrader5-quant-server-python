import os
import logging
import asyncio
import json
from pybit.unified_trading import HTTP
from app.utils.redis_client import get_redis_connection
from dotenv import load_dotenv
from decimal import Decimal
from datetime import datetime, timezone, timedelta

load_dotenv()
logger = logging.getLogger(__name__)
redis_conn = get_redis_connection()

session = HTTP(
    testnet=False,
    api_key=os.environ.get('API_KEY_BYBIT'),
    api_secret=os.environ.get('API_SECRET_BYBIT'),
)


class json_encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return json.JSONEncoder.default(self, obj)


def prepare_json(json_str, default_value):
    if json_str is None:
        return default_value
    return json.loads(json_str)


def clean_val(val):
    if isinstance(val, bytes):
        val = val.decode('utf-8')
    try:
        return float(val) if val is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


async def subscribe_position_information(symbol: str):
    logger.info(f"Starting bybit position subscription for {symbol}.")
    while True:
        try:
            response = session.get_positions(category="linear", symbol=symbol)

            if response.get('retCode') != 0:
                logger.error(f"Position information error: {response.get('retMsg')}")
                await asyncio.sleep(1)
                continue

            positions_list = response.get('result', {}).get('list', [])
            redis_key = f"position:bybit:{symbol}"

            open_position = next(
                (p for p in positions_list if float(p.get('size', 0)) != 0),
                None
            )

            if open_position:
                thailand_tz = timezone(timedelta(hours=7))
                latest_update = datetime.now(thailand_tz).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

                position_data = {
                    "symbol": open_position.get('symbol'),
                    "positionAmt": open_position.get('size'),
                    "entryPrice": open_position.get('avgPrice'),
                    "markPrice": open_position.get('markPrice'),
                    "unRealizedProfit": open_position.get('unrealisedPnl'),
                    "side": open_position.get('side'),
                    "updateTime": latest_update,
                }

                redis_conn.set(redis_key, json.dumps(position_data))
                redis_conn.publish(redis_key, json.dumps(position_data))
                redis_conn.expire(redis_key, 10)
            else:
                if redis_conn.exists(redis_key):
                    redis_conn.delete(redis_key)

            await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.error(f"Position task for {symbol} cancelled.")
            break
        except Exception as e:
            logger.error(f"Position information subscription error for {symbol}: {e}. Retrying in 1 second...")
            await asyncio.sleep(1)



async def subscribe_spread_diff(bybit_symbol: str, mt5_symbol: str):
    logger.info(f"Starting bybit spread diff subscription for {bybit_symbol}/{mt5_symbol}.")
    while True:
        try:
            ticker_bybit_key = f"ticker:bybit:{bybit_symbol}"
            ticker_mt5_key = f"ticker:mt5:{mt5_symbol}"

            raw_ticker_bybit = redis_conn.hgetall(ticker_bybit_key)
            ticker_bybit = raw_ticker_bybit if raw_ticker_bybit else {}
            ticker_mt5 = prepare_json(redis_conn.get(ticker_mt5_key), {})

            bybit_best_bid = clean_val(ticker_bybit.get(b'best_bid' if b'best_bid' in ticker_bybit else 'best_bid'))
            bybit_best_ask = clean_val(ticker_bybit.get(b'best_ask' if b'best_ask' in ticker_bybit else 'best_ask'))
            mt5_best_bid = clean_val(ticker_mt5.get('best_bid'))
            mt5_best_ask = clean_val(ticker_mt5.get('best_ask'))

            current_upper_diff = round(bybit_best_ask - mt5_best_bid, 2)
            current_lower_diff = round(bybit_best_bid - mt5_best_ask, 2)

            grid_bot_boundary_key = f"spread:bybit:{bybit_symbol}"
            redis_conn.set(grid_bot_boundary_key, json.dumps({
                "current_upper_diff": current_upper_diff,
                "current_lower_diff": current_lower_diff,
            }))
            redis_conn.publish(grid_bot_boundary_key, json.dumps({
                "current_upper_diff": current_upper_diff,
                "current_lower_diff": current_lower_diff,
            }))
            redis_conn.expire(grid_bot_boundary_key, 10)

            await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.error(f"Spread diff task for {bybit_symbol}/{mt5_symbol} cancelled.")
            break
        except Exception as e:
            logger.error(f"Spread diff error for {bybit_symbol}/{mt5_symbol}: {e}. Retrying in 1 second...")
            await asyncio.sleep(1)


def get_position(symbol: str):
    redis_key = f"position:bybit:{symbol}"
    position_data = redis_conn.get(redis_key)
    if position_data:
        return json.loads(position_data)
    return None
