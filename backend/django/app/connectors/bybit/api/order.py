import os
import logging
import time
from dotenv import load_dotenv
from pybit.unified_trading import HTTP
from .ticker import get_ticker

load_dotenv()
logger = logging.getLogger(__name__)

session = HTTP(
    testnet=False,
    api_key=os.environ.get('API_KEY_BYBIT'),
    api_secret=os.environ.get('API_SECRET_BYBIT'),
)


def new_order(symbol, quantity, price, side):
    try:
        bybit_side = "Buy" if side.upper() == "BUY" else "Sell"
        response = session.place_order(
            category="linear",
            symbol=symbol,
            side=bybit_side,
            orderType="Limit",
            qty=str(quantity),
            price=str(price),
            timeInForce="PostOnly",
        )
        if response.get('retCode') != 0:
            logger.error(f"New order error (Post-only might have been rejected if price matches immediately): {response.get('retMsg')}")
            return None
        return response.get('result')
    except Exception as e:
        logger.error(f"New order error (Post-only might have been rejected if price matches immediately): {e}")
        return None


def cancel_all_open_orders(symbol):
    try:
        response = session.cancel_all_orders(
            category="linear",
            symbol=symbol,
        )
        if response.get('retCode') != 0:
            logger.error(f"Cancel all open orders error: {response.get('retMsg')}")
        return response.get('result')
    except Exception as e:
        logger.error(f"Cancel all open orders error: {e}")


def get_open_orders(symbol):
    try:
        response = session.get_open_orders(
            category="linear",
            symbol=symbol,
        )
        if response.get('retCode') != 0:
            logger.error(f"Get open orders error: {response.get('retMsg')}")
            return []
        return response.get('result', {}).get('list', [])
    except Exception as e:
        logger.error(f"Get open orders error: {e}")
        return []


def chase_order(symbol, quantity, side, max_retries=6, delay=1):
    for attempt in range(max_retries):
        try:
            ticker = get_ticker(symbol)
            if not ticker:
                logger.warning(f"Ticker data not available for symbol={symbol}. Retrying...")
                time.sleep(delay)
                continue

            target_price = float(ticker['best_bid']) if side.upper() == "BUY" else float(ticker['best_ask'])

            open_orders = get_open_orders(symbol)
            matching_order = next(
                (order for order in open_orders if round(float(order.get('price', 0)), 4) == float(target_price)),
                None
            )
            if matching_order:
                return matching_order
            else:
                if open_orders:
                    cancel_all_open_orders(symbol)

                order_result = new_order(symbol=symbol, quantity=quantity, price=target_price, side=side)
                if not order_result:
                    logger.warning(f"Post-only order rejected at {target_price}. Will retry in next loop.")
        except Exception as e:
            logger.error(f"Chase order error on attempt {attempt + 1}: {e}")
            break

    logger.error(f"Chase order failed after {max_retries} attempts.")


def get_latest_order_snapshot(symbol):
    """
    Fetches the most recent order and determines if it is 'Clean'
    """
    try:
        response = session.get_order_history(
            category="linear",
            symbol=symbol,
            limit=1,
        )
        if response.get('retCode') != 0:
            logger.error(f"Get order history error: {response.get('retMsg')}")
            return None

        orders = response.get('result', {}).get('list', [])
        if not orders:
            return {"status": "NONE", "is_clean": True, "fill_pct": 0}

        latest = orders[0]
        status = latest.get('orderStatus')
        orig_qty = float(latest.get('qty', 0))
        executed_qty = float(latest.get('cumExecQty', 0))
        fill_pct = (executed_qty / orig_qty) * 100 if orig_qty > 0 else 0

        terminal_statuses = ['Filled', 'Cancelled', 'Rejected', 'PartiallyFilledCanceled', 'Deactivated']
        is_clean = status in terminal_statuses

        return {
            "order_id": latest.get('orderId'),
            "status": status,
            "is_clean": is_clean,
            "fill_pct": fill_pct,
            "side": latest.get('side'),
        }
    except Exception as e:
        logger.error(f"Error fetching order snapshot: {e}")
        return None
