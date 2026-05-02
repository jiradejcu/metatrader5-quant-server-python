import os
import logging
import asyncio
import pandas as pd
import json
from app.utils.redis_client import get_redis_connection
from app.utils.api.data import symbol_info_tick
from dotenv import load_dotenv
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL,
    ConfigurationWebSocketAPI,
)

load_dotenv()
logger = logging.getLogger(__name__)

configuration_ws_api = ConfigurationWebSocketAPI(
    api_key=os.environ.get('API_KEY_BINANCE'),
    api_secret=os.environ.get('API_SECRET_BINANCE'),
    stream_url=os.getenv(
        "STREAM_URL", DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL
    ),
)

client = DerivativesTradingUsdsFutures(config_ws_api=configuration_ws_api)
redis_conn = get_redis_connection()


class json_encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return json.JSONEncoder.default(self, obj)


async def subscribe_position_information(symbol: str):
    logger.info(f"Starting binance position subscription for {symbol}.")
    while True:
        connection = None
        try:
            connection = await client.websocket_api.create_connection()
            logger.info(f"WebSocket connection for {symbol} position information established.")

            while True:
                response = await connection.position_information()

                positions_list = response.data().result
                positions_as_dicts = [p.to_dict() for p in positions_list]
                df = pd.DataFrame(positions_as_dicts)

                df['positionAmt'] = pd.to_numeric(df['positionAmt'])
                symbol_open_position_df = df[(df['symbol'] == symbol)]

                redis_key = f"position:binance:{symbol}"

                if not symbol_open_position_df.empty:
                    position_data = symbol_open_position_df.iloc[0].to_dict()

                    thailand_tz = timezone(timedelta(hours=7))
                    latest_update = datetime.now(thailand_tz).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    position_data['updateTime'] = latest_update

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
        finally:
            if connection:
                try:
                    logger.warning(f"Closing WebSocket connection for {symbol} position information...")
                    await connection.close_connection(close_session=True)
                except Exception as close_err:
                    logger.warning(f"Error while closing connection for {symbol}: {close_err}")


def get_position(symbol: str):
    redis_key = f"position:binance:{symbol}"
    position_data = redis_conn.get(redis_key)
    if position_data:
        return json.loads(position_data)
    return None
