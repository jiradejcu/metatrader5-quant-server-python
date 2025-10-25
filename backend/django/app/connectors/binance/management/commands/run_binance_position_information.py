import os
import logging
import asyncio
import pandas as pd
from dotenv import load_dotenv
from django.core.management.base import BaseCommand
from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL,
    ConfigurationWebSocketAPI,
)

load_dotenv()
api_key = os.environ.get('API_KEY_BINANCE')
api_secret = os.environ.get('API_SECRET_BINANCE')

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

configuration_ws_api = ConfigurationWebSocketAPI(
    api_key=api_key,
    api_secret=api_secret,
    stream_url=os.getenv(
        "STREAM_URL", DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL
    ),
)

client = DerivativesTradingUsdsFutures(config_ws_api=configuration_ws_api)

async def position_information():
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
                print(open_positions[existing_relevant_columns])
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


class Command(BaseCommand):
    def handle(self, *args, **options):
        logger.info(self.style.SUCCESS("Connecting to Binance WebSocket for position information..."))
        asyncio.run(position_information())
