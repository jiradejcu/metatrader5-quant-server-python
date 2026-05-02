import os
import logging
import asyncio
import json
from pybit.unified_trading import HTTP
from app.utils.redis_client import get_redis_connection
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta

load_dotenv()
logger = logging.getLogger(__name__)
redis_conn = get_redis_connection()

session = HTTP(
    testnet=False,
    api_key=os.environ.get('API_KEY_BYBIT'),
    api_secret=os.environ.get('API_SECRET_BYBIT'),
)

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

            await asyncio.sleep(0.2)

        except asyncio.CancelledError:
            logger.error(f"Position task for {symbol} cancelled.")
            break
        except Exception as e:
            logger.error(f"Position information subscription error for {symbol}: {e}. Retrying in 1 second...")
            await asyncio.sleep(1)


def get_position(symbol: str):
    redis_key = f"position:bybit:{symbol}"
    position_data = redis_conn.get(redis_key)
    if position_data:
        return json.loads(position_data)
    return None
