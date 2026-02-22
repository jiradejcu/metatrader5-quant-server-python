import os
import logging
import time
from dotenv import load_dotenv
from .ticker import get_ticker

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
        logger.info(f"{NewOrderTimeInForceEnum}")
        response = client.rest_api.new_order(
            symbol=symbol,
            quantity=quantity,
            price=price,
            side=NewOrderSideEnum[side].value,
            type="LIMIT",  # Use LIMIT_MAKER to ensure post-only behavior
            time_in_force=NewOrderTimeInForceEnum["GTX"].value,
        )

        rate_limits = response.rate_limits
        logger.info(f"New order rate limits: {rate_limits}")

        data = response.data()
        logger.info(f"New order response: {data}")
        
        return data
    except Exception as e:
        logger.error(f"New order error (Post-only might have been rejected if price matches immediately): {e}")
        return None

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

def chase_order(symbol, quantity, side, max_retries=6, delay=10):
    for attempt in range(max_retries):
        try:
            ticker = get_ticker(symbol)
            if not ticker:
                logger.warning(f"Ticker data not available for symbol={symbol}. Retrying...")
                time.sleep(delay)
                continue

            target_price = float(ticker['best_bid']) if side == "BUY" else float(ticker['best_ask'])
            logger.info(f"Chase order attempt {attempt + 1}: Placing {side} order for {quantity} {symbol} at price {target_price}")

            open_orders = get_open_orders(symbol)
            matching_order = next((order for order in open_orders if round(float(getattr(open_orders[0], 'price', 0)), 4) == float(target_price)), None)
            if matching_order:
                logger.info(f"Matching order already exists at price {target_price}. No new order placed.")
                return matching_order
            else:
                if open_orders:
                    logger.info(f"Price moved to {target_price}. Cancelling old orders...")
                    cancel_all_open_orders(symbol)

                order_result = new_order(
                    symbol=symbol, 
                    quantity=quantity, 
                    price= target_price, 
                    side=side
                    )
                if not order_result:
                    logger.warning(f"Post-only order rejected at {target_price}. Will retry in next loop.")
                else:
                    logger.info(f"Post-only order placed successfully: {order_result.get('orderId')}")
            time.sleep(delay)
        except Exception as e:
            logger.error(f"Chase order error on attempt {attempt + 1}: {e}")
            break

    logger.error(f"Chase order failed after {max_retries} attempts.")