import os
import requests
import traceback
from typing import List, Dict, Optional, Tuple
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
import logging

from app.utils.constants import MT5Timeframe
from app.utils.api.data import symbol_info_tick
from app.nexus.models import Trade, TradeClosePricesMutation  # Import models
from app.utils.arithmetics import get_pnl_at_price, calculate_commission, get_price_at_pnl, calculate_order_capital, calculate_order_size_usd

load_dotenv()
logger = logging.getLogger(__name__)

BASE_URL = os.getenv('MT5_API_URL')

def send_market_order(symbol: str, volume: float = None, order_type: str = None, sl: float = None, tp: float = None, position: int = None, position_by: int = None, comment: str = '') -> Tuple[Optional[Dict], Optional[Dict]]:
    """Send a market (or close-by) order to MT5. Returns (order, error).

    On success: (order, None). On failure: (None, error) where error is
    {retcode, comment, http_status}. retcode is the MT5 TRADE_RETCODE_* value
    when the MT5 server actually rejected the order, or None when the failure
    happened before reaching the broker (bad request, MT5 unavailable, timeout,
    transport error) — callers use it to tell market-condition rejections apart
    from everything else.
    """
    def _error(comment, retcode=None, http_status=None):
        return None, {"retcode": retcode, "comment": comment, "http_status": http_status}

    try:
        request = {
            "symbol": symbol,
            "comment": comment,
        }

        if position_by is not None:
            request["position"] = position
            request["position_by"] = position_by
            request["type"] = "BUY" # type is ignored for close_by in backend but required by validation
            # Even though volume is ignored by backend for close_by, it might be required by field validation
            request["volume"] = 0
        else:
            if order_type is None or volume is None:
                error_msg = "order_type and volume are required for market orders"
                logger.error(error_msg)
                return _error(error_msg)

            order_type_str = order_type if isinstance(order_type, str) else order_type.name

            if order_type_str not in ['BUY', 'SELL']:
                error_msg = f"Invalid order type: {order_type_str}. Must be 'BUY' or 'SELL'"
                logger.error(error_msg)
                return _error(error_msg)

            request["volume"] = float(volume)
            request["type"] = 0 if order_type_str == 'BUY' else 1

            if sl is not None:
                request["sl"] = float(sl)

            if tp is not None:
                request["tp"] = float(tp)

            if position is not None:
                request["position"] = position

        logger.info(f"Sending order request: {request}")

        url = f"{BASE_URL}/order"
        response = requests.post(url, json=request, timeout=10)
        response.raise_for_status()

        response_data = response.json()
        
        if response_data.get('error'):
            error_msg = response_data.get('error', 'Unknown error')
            logger.error(f"Order failed: {error_msg}")
            retcode = (response_data.get('result') or {}).get('retcode')
            return _error(error_msg, retcode=retcode, http_status=response.status_code)
            
        order = response_data['result']
        logger.info(f"Order successful: {order}")

        # Broker may return price=0 for async fills; fall back to the requested
        # price (MqlTradeRequest index 5) which is the bid/ask at submission time.
        if not order.get('price') and isinstance(order.get('request'), list):
            order['price'] = order['request'][5]

        return order, None
        
    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP error sending order for {symbol}: {e.response.text}"
        logger.error(error_msg)
        # The MT5 /order endpoint answers a broker rejection with HTTP 400 and
        # {"error", "mt5_error", "result": {"retcode", ...}}.
        retcode = None
        try:
            retcode = (e.response.json().get('result') or {}).get('retcode')
        except Exception:
            pass
        return _error(error_msg, retcode=retcode, http_status=e.response.status_code)

    except requests.exceptions.Timeout:
        error_msg = f"Timeout sending order for {symbol}"
        logger.error(error_msg)
        return _error(error_msg)
    
    except Exception as e:
        error_msg = f"Exception sending order for {symbol}: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        return _error(error_msg)

def close_by(symbol: str, ticket: int, ticket_by: int) -> Tuple[Optional[Dict], Optional[Dict]]:
    return send_market_order(symbol=symbol, position=ticket, position_by=ticket_by)

def validate_order(symbol: str, order_type: str, volume: float, sl: float = None, tp: float = None) -> Dict:
    """Dry-run a market order against MT5 (mt5.order_check()) without sending it.

    Returns {ok, retcode, comment, margin_required, free_margin_after} on success.
    On any transport/API failure returns {ok: False, comment: <reason>} so callers
    can treat unreachable MT5 the same as a failed check and skip placing the order.
    """
    order_type_str = order_type if isinstance(order_type, str) else order_type.name
    if order_type_str not in ['BUY', 'SELL']:
        error_msg = f"Invalid order type: {order_type_str}. Must be 'BUY' or 'SELL'"
        logger.error(error_msg)
        return {"ok": False, "comment": error_msg}

    request = {
        "symbol": symbol,
        "volume": float(volume),
        "type": order_type_str,
    }
    if sl is not None:
        request["sl"] = float(sl)
    if tp is not None:
        request["tp"] = float(tp)

    try:
        url = f"{BASE_URL}/validate_order"
        response = requests.post(url, json=request, timeout=10)
        response.raise_for_status()
        result = response.json()

        if 'ok' not in result:
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"Validate order failed for {symbol}: {error_msg}")
            return {"ok": False, "comment": error_msg}

        if not result.get('ok'):
            logger.warning(f"Validate order rejected for {symbol}: {result.get('comment')}")
        else:
            logger.info(f"Validate order passed for {symbol}: {result}")

        return result

    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP error validating order for {symbol}: {e.response.text}"
        logger.error(error_msg)
        return {"ok": False, "comment": error_msg}

    except requests.exceptions.Timeout:
        error_msg = f"Timeout validating order for {symbol}"
        logger.error(error_msg)
        return {"ok": False, "comment": error_msg}

    except Exception as e:
        error_msg = f"Exception validating order for {symbol}: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        return {"ok": False, "comment": error_msg}
    
def modify_sl_tp(position, sl: float, tp: float = None) -> Dict:
    try:
        request = {
            "ticket": position.ticket,
            "symbol": position.symbol,
            'type': position.type,
            "sl": float(sl),
        }

        if tp is not None:
            request['tp'] = float(tp)

        logger.info(f"Sending modify SL/TP request: {request}")

        url = f"{BASE_URL}/modify_sl_tp"
        response = requests.post(url, json=request, timeout=10)
        response.raise_for_status()

        response_data = response.json()

        if not response_data.get('success'):
            error_msg = response_data.get('error', 'Unknown error')
            details = response_data.get('details', '')
            logger.error(f"Modify SL/TP failed: {error_msg} {details}")
            return None

        result = response_data.get('result')
        if result:
            logger.info(f"Modify SL/TP successful: {result}")
            return result
        else:
            logger.error("No result returned from modify_sl_tp endpoint.")
            return None

    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP error sending modify SL/TP for {position.ticket}: {e.response.text}"
        logger.error(error_msg)
       
    except requests.exceptions.Timeout:
        error_msg = f"Timeout sending modify SL/TP for {position.ticket}"
        logger.error(error_msg)
        return None
    
    except Exception as e:
        error_msg = f"Exception sending modify SL/TP for {position.ticket}: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)