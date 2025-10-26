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

async def subscribe_position_information(symbol: str):
    connection = None
    try:
        connection = await client.websocket_api.create_connection()

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

            existing_relevant_columns = [col for col in relevant_columns if col in df.columns]
            df['positionAmt'] = pd.to_numeric(df['positionAmt'])
            open_positions = df[df['positionAmt'] != 0]

            if not open_positions.empty:
                # print(open_positions[existing_relevant_columns])
                symbol_position_df = open_positions[open_positions['symbol'] == symbol]
                redis_conn = get_redis_connection()
                redis_key = f"position:{symbol}"
                if not symbol_position_df.empty:
                    position_data = symbol_position_df.iloc[0].to_dict()
                    redis_conn.set(redis_key, json.dumps(position_data))
                    logger.debug(f"Updated Redis {redis_key} with position data.")
                else:
                    redis_conn.delete(redis_key) # No position, so remove the key
            else:
                logger.info("No open positions found.")

            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info("WebSocket task cancelled. Closing connection.")
    except Exception as e:
        logger.error(f"position_information() error: {e}")
    finally:
        if connection:
            logger.info("Closing WebSocket connection...")
            await connection.close_connection(close_session=True)
