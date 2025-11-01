import os
import logging
from dotenv import load_dotenv

from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    ConfigurationRestAPI,
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
)
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    NewOrderSideEnum,
    NewOrderTimeInForceEnum,
)

load_dotenv()
logger = logging.getLogger(__name__)

configuration_rest_api = ConfigurationRestAPI(
    api_key=os.environ.get('API_KEY_BINANCE'),
    api_secret=os.environ.get('API_SECRET_BINANCE'),
    base_path=os.getenv(
        "BASE_PATH", DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL
    ),
)

client = DerivativesTradingUsdsFutures(config_rest_api=configuration_rest_api)

def new_order(symbol, quantity, price, side):
    try:
        logger.info(f"New order being placed: symbol={symbol}, quantity={quantity}, price={price}, side={side}")
        response = client.rest_api.new_order(
            symbol=symbol,
            quantity=quantity,
            price=price,
            side=NewOrderSideEnum[side].value,
            type="LIMIT",
            time_in_force=NewOrderTimeInForceEnum["GTC"].value,
        )

        rate_limits = response.rate_limits
        logger.info(f"New order rate limits: {rate_limits}")

        data = response.data()
        logger.info(f"New order response: {data}")
        
        return data
    except Exception as e:
        logger.error(f"New order error: {e}")

def cancel_all_open_orders(symbol):
    try:
        logger.info(f"Cancel all open order: symbol={symbol}")
        response = client.rest_api.cancel_all_open_orders(
            symbol=symbol,
        )

        rate_limits = response.rate_limits
        logger.info(f"Cancel all open order rate limits: {rate_limits}")

        data = response.data()
        logger.info(f"Cancel all open order response: {data}")
        
        return data
    except Exception as e:
        logger.error(f"Cancel all open order error: {e}")

def get_open_orders(symbol):
    try:
        logger.info(f"Get open orders for symbol={symbol}")
        response = client.rest_api.current_all_open_orders(
            symbol=symbol,
        )

        rate_limits = response.rate_limits
        logger.info(f"Get open orders rate limits: {rate_limits}")

        data = response.data()
        logger.info(f"Get open orders response: {data}")
        
        return data
    except Exception as e:
        logger.error(f"Get open orders error: {e}")