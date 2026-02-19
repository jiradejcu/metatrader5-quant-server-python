import os
import requests
import traceback
from typing import List, Dict
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

def send_market_order(symbol: str, volume: float = None, order_type: str = None, sl: float = None, tp: float = None, position: int = None, position_by: int = None) -> Dict:
    try:
        request = {
            "symbol": symbol,
        }

        if position_by is not None:
            request["position"] = position
            request["position_by"] = position_by
            request["type"] = "BUY" # type is ignored for close_by in backend but required by validation
            # Even though volume is ignored by backend for close_by, it might be required by field validation
            request["volume"] = 0 
        else:
            if order_type is None or volume is None:
                logger.error("order_type and volume are required for market orders")
                return None
                
            order_type_str = order_type if isinstance(order_type, str) else order_type.name
            
            if order_type_str not in ['BUY', 'SELL']:
                error_msg = f"Invalid order type: {order_type_str}. Must be 'BUY' or 'SELL'"
                logger.error(error_msg)
                return None

            request["volume"] = float(volume)
            request["type"] = order_type_str
            
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
            return None
            
        order = response_data['result']
        logger.info(f"Order successful: {order}")

        return order
        
    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP error sending order for {symbol}: {e.response.text}"
        logger.error(error_msg)

    except requests.exceptions.Timeout:
        error_msg = f"Timeout sending order for {symbol}"
        logger.error(error_msg)
    
    except Exception as e:
        error_msg = f"Exception sending order for {symbol}: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)

def close_by(symbol: str, ticket: int, ticket_by: int) -> Dict:
    return send_market_order(symbol=symbol, position=ticket, position_by=ticket_by)
    
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