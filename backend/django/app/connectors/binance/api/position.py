import os
import logging
import asyncio
import pandas as pd
from dotenv import load_dotenv

from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL,
    ConfigurationWebSocketAPI,
)

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

configuration_ws_api = ConfigurationWebSocketAPI(
    api_key=os.environ.get('API_KEY_BINANCE'),
    api_secret=os.environ.get('API_SECRET_BINANCE'),
    stream_url=os.getenv(
        "STREAM_URL", DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL
    ),
)

client = DerivativesTradingUsdsFutures(config_ws_api=configuration_ws_api)

SYMBOL_POSITION = None

async def subscribe_position_information(symbol: str):
    connection = None
    try:
        connection = await client.websocket_api.create_connection()

        while True:
            response = await connection.position_information()

            rate_limits = response.rate_limits
            logging.info(f"position_information() rate limits: {rate_limits}")

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

            logging.info("Open Positions Only:")
            if not open_positions.empty:
                global SYMBOL_POSITION
                print(open_positions[existing_relevant_columns])
                symbol_position_df = open_positions[open_positions['symbol'] == symbol]
                if not symbol_position_df.empty:
                    SYMBOL_POSITION = symbol_position_df.iloc[0].to_dict()
                else:
                    SYMBOL_POSITION = None
            else:
                logging.info("No open positions found.")

            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logging.info("WebSocket task cancelled. Closing connection.")
    except Exception as e:
        logging.error(f"position_information() error: {e}")
    finally:
        if connection:
            logging.info("Closing WebSocket connection...")
            await connection.close_connection(close_session=True)
