import os
import logging
import asyncio
import pandas as pd
import json
from app.utils.redis_client import get_redis_connection
from dotenv import load_dotenv

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

async def subscribe_position_information(symbol: str):
    connection = None
    try:
        connection = await client.websocket_api.create_connection()
        logger.info("WebSocket connection for position information established.")

        while True:
            response = await connection.position_information()

            rate_limits = response.rate_limits
            logger.debug(f"position_information() rate limits: {rate_limits}")

            positions_list = response.data().result
            positions_as_dicts = [p.to_dict() for p in positions_list]
            df = pd.DataFrame(positions_as_dicts)

            relevant_columns = [
                'symbol',
                'positionAmt',
                'entryPrice',
                'markPrice',
                'unRealizedProfit',
                'leverage',
                'liquidationPrice'
            ]

            df['positionAmt'] = pd.to_numeric(df['positionAmt'])
            symbol_open_position_df = df[(df['symbol'] == symbol) & (df['positionAmt'] != 0)]

            redis_key = f"position:{symbol}"

            if not symbol_open_position_df.empty:
                logger.debug(symbol_open_position_df[relevant_columns].to_json(orient='records'))
                position_data = symbol_open_position_df.iloc[0].to_dict()
                redis_conn.set(redis_key, json.dumps(position_data))
                redis_conn.publish(redis_key, json.dumps(position_data))
                logger.debug(f"Updated Redis {redis_key} with position data.")
            else:
                if redis_conn.exists(redis_key):
                    redis_conn.delete(redis_key)
                    logger.debug(f"Deleted Redis key {redis_key} as no open position found for {symbol}.")

            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info("WebSocket task cancelled. Closing connection.")
    except Exception as e:
        logger.error(f"Position information subscription error: {e}")
    finally:
        if connection:
            logger.info("Closing WebSocket connection...")
            await connection.close_connection(close_session=True)

def get_position(symbol: str):
    redis_key = f"position:{symbol}"
    position_data = redis_conn.get(redis_key)
    if position_data:
        return json.loads(position_data)
    return None