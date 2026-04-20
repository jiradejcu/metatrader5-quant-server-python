import os
import logging
from dotenv import load_dotenv

from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    ConfigurationRestAPI,
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL
)
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    NewOrderSideEnum,
    NewOrderTimeInForceEnum,
    ModifyOrderSideEnum,
    ModifyOrderPriceMatchEnum,
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
        # logger.info(f"New order being placed: symbol={symbol}, quantity={quantity}, price={price}, side={side}")
        # logger.info(f"{NewOrderTimeInForceEnum}")
        response = client.rest_api.new_order(
            symbol=symbol,
            quantity=quantity,
            price=price,
            side=NewOrderSideEnum[side].value,
            type="LIMIT",  # Use LIMIT_MAKER to ensure post-only behavior
            time_in_force=NewOrderTimeInForceEnum["GTX"].value,
        )

        rate_limits = response.rate_limits
        # logger.info(f"New order rate limits: {rate_limits}")

        data = response.data()
        # logger.info(f"New order response: {data}")
        
        return data
    except Exception as e:
        logger.error(f"New order error (Post-only might have been rejected if price matches immediately): {e}")
        return None

def cancel_all_open_orders(symbol):
    try:
        # logger.info(f"Cancel all open order: symbol={symbol}")
        response = client.rest_api.cancel_all_open_orders(
            symbol=symbol,
        )

        rate_limits = response.rate_limits
        # logger.info(f"Cancel all open order rate limits: {rate_limits}")

        data = response.data()
        # logger.info(f"Cancel all open order response: {data}")
        
        return data
    except Exception as e:
        logger.error(f"Cancel all open order error: {e}")

def get_open_orders(symbol):
    try:
        # logger.info(f"Get open orders for symbol={symbol}")
        response = client.rest_api.current_all_open_orders(
            symbol=symbol,
        )

        rate_limits = response.rate_limits
        # logger.info(f"Get open orders rate limits: {rate_limits}")

        data = response.data()
        # logger.info(f"Get open orders response: {data}")
        
        return data
    except Exception as e:
        logger.error(f"Get open orders error: {e}")

def chase_order(symbol, quantity, side):
    try:
        open_orders = get_open_orders(symbol)
        if open_orders:
            order_id = getattr(open_orders[0], 'order_id', None)
            response = client.rest_api.modify_order(
                symbol=symbol,
                side=ModifyOrderSideEnum[side].value,
                quantity=quantity,
                price=None,
                order_id=order_id,
                price_match=ModifyOrderPriceMatchEnum["OPPONENT"].value,
            )
        else:
            response = client.rest_api.new_order(
                symbol=symbol,
                quantity=quantity,
                side=NewOrderSideEnum[side].value,
                type="LIMIT",
                time_in_force=NewOrderTimeInForceEnum["GTX"].value,
                price_match="OPPONENT",
            )
        return response.data()
    except Exception as e:
        logger.error(f"Chase order error: {e}")
        return None

def get_latest_order_snapshot(symbol):
    """
    Fetches the most recent order as an object and determines if it is 'Clean'
    """
    try:
        # The query time period must be less then 7 days( default as the recent 7 days).
        response = client.rest_api.all_orders(symbol=symbol, limit=1)
        orders = response.data() # This returns a list of AllOrdersResponse objects

        if not orders or len(orders) == 0:
            return {"status": "NONE", "is_clean": True, "fill_pct": 0}

        # Access the latest order via index, then use dot notation
        latest = orders[0]
        # logger.debug(f'Snapshot order object: {latest}')

        status = latest.status
        orig_qty = float(latest.orig_qty)
        executed_qty = float(latest.executed_qty)
        
        fill_pct = (executed_qty / orig_qty) * 100 if orig_qty > 0 else 0

        # Define Clean/Dirty logic
        # Clean: The order is finished. We can safely open a new one.
        # Dirty: NEW or PARTIALLY_FILLED. We must wait to avoid double-ordering.
        terminal_statuses = ['FILLED', 'CANCELED', 'EXPIRED', 'REJECTED', 'EXPIRED_IN_MATCH']
        is_clean = status in terminal_statuses

        # logger.debug(f"[Binance snapshot] Order {latest.order_id} status: {status}, Clean: {is_clean}, qty: {latest.orig_qty}, price: {latest.price}")

        return {
            "order_id": latest.order_id,
            "status": status,
            "is_clean": is_clean,
            "fill_pct": fill_pct,
            "side": latest.side
        }
    except Exception as e:
        logger.error(f"Error fetching order snapshot: {e}")
        return None