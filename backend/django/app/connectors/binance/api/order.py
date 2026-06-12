import os
import json
import logging
import types
from dotenv import load_dotenv
from app.utils.redis_client import get_redis_connection

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
    ModifyOrderResponse,
)
from binance_common.utils import send_request

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

redis_conn = get_redis_connection()


def fetch_open_orders_from_api(symbol):
    """Force-fetch open orders from Binance REST API and refresh Redis cache."""
    try:
        response = client.rest_api.current_all_open_orders(symbol=symbol)
        open_order_data = response.data() or []
        redis_key = f"open_orders:binance:{symbol}"
        # Use field names (order_id, orig_qty, ...), not to_dict()'s camelCase
        # aliases (orderId, origQty, ...), so cached SimpleNamespace objects
        # expose the same snake_case attributes as the live SDK objects
        # returned on the force-fetch path (see _reconcile).
        redis_conn.set(redis_key, json.dumps([o.model_dump(mode="json") for o in open_order_data]))
        redis_conn.expire(redis_key, 60)
        logger.debug(f"[OpenOrders] Force-fetched from API: {symbol} count={len(open_order_data)}")
        return open_order_data
    except Exception as e:
        logger.error(f"Get open orders error: {e}")
        return None


def get_open_orders(symbol, force=False):
    if force:
        return fetch_open_orders_from_api(symbol)
    redis_key = f"open_orders:binance:{symbol}"
    open_order_data = redis_conn.get(redis_key)
    if open_order_data:
        return [types.SimpleNamespace(**o) for o in json.loads(open_order_data)]
    return fetch_open_orders_from_api(symbol)

def _modify_order_with_price_match(symbol, side, quantity, order_id, price_match):
    # The SDK's modify_order() hard-rejects price=None, but send_request strips
    # None values before the HTTP call, so price_match works correctly this way.
    trade_api = client.rest_api._tradeApi
    return send_request(
        trade_api._session,
        trade_api._configuration,
        method="PUT",
        path="/fapi/v1/order",
        payload={
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": None,
            "order_id": order_id,
            "price_match": price_match,
        },
        body={},
        time_unit=trade_api._configuration.time_unit,
        response_model=ModifyOrderResponse,
        is_signed=True,
        signer=trade_api._signer,
    )

def chase_order(symbol, quantity, side, order_id=None):
    """Chase a limit order at QUEUE price match.

    Args:
        order_id: When provided, modify that specific open order in-place.
                  When None, place a brand-new GTX limit order.

    The caller (``_reconcile``) is responsible for deciding which path to take
    based on the open-orders snapshot it already holds.  This function never
    calls ``get_open_orders`` internally, which eliminates the fill-race window
    where an order could be placed silently after the real order had already
    filled — bypassing ATR and capacity checks in ``_process_tick``.
    """
    try:
        if order_id is not None:
            response = _modify_order_with_price_match(
                symbol=symbol,
                side=ModifyOrderSideEnum[side].value,
                quantity=quantity,
                order_id=order_id,
                price_match=ModifyOrderPriceMatchEnum["QUEUE"].value,
            )
            data = response.data()
            logger.info(
                f"Chase order modified: order_id={order_id} side={side} qty={quantity} "
                f"price → {getattr(data, 'price', None)}"
            )
        else:
            response = client.rest_api.new_order(
                symbol=symbol,
                quantity=quantity,
                side=NewOrderSideEnum[side].value,
                type="LIMIT",
                time_in_force=NewOrderTimeInForceEnum["GTX"].value,
                price_match="QUEUE",
            )
            data = response.data()
            logger.info(
                f"Chase order placed: order_id={getattr(data, 'order_id', None)} "
                f"side={side} qty={quantity} price={getattr(data, 'price', None)}"
            )
        return data
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