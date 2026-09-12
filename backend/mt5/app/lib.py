import MetaTrader5 as mt5
from datetime import datetime, timedelta
from typing import List, Dict
import pandas as pd
from constants import MT5Timeframe
import logging

logger = logging.getLogger(__name__)

def get_timeframe(timeframe_str: str) -> MT5Timeframe:
    try:
        return MT5Timeframe[timeframe_str.upper()].value
    except KeyError:
        valid_timeframes = ', '.join([t.name for t in MT5Timeframe])
        raise ValueError(
            f"Invalid timeframe: '{timeframe_str}'. Valid options are: {valid_timeframes}."
        )


def close_position(position, deviation=20, magic=0, comment='', type_filling=mt5.ORDER_FILLING_IOC):
    if 'type' not in position or 'ticket' not in position:
        logger.error("Position dictionary missing 'type' or 'ticket' keys.")
        return None

    order_type_dict = {
        0: mt5.ORDER_TYPE_BUY,
        1: mt5.ORDER_TYPE_SELL
    }

    position_type = position['type']
    if position_type not in order_type_dict:
        logger.error(f"Unknown position type: {position_type}")
        return None

    tick = mt5.symbol_info_tick(position['symbol'])
    if tick is None:
        logger.error(f"Failed to get tick for symbol: {position['symbol']}")
        return None

    price_dict = {
        0: tick.ask,  # Buy order uses Ask price
        1: tick.bid   # Sell order uses Bid price
    }

    price = price_dict[position_type]
    if price == 0.0:
        logger.error(f"Invalid price retrieved for symbol: {position['symbol']}")
        return None

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": position['ticket'],  # select the position you want to close
        "symbol": position['symbol'],
        "volume": position['volume'],  # FLOAT
        "type": order_type_dict[position_type],
        "price": price,
        "deviation": deviation,  # INTEGER
        "magic": magic,          # INTEGER
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": type_filling,
    }

    order_result = mt5.order_send(request)

    if order_result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Failed to close position {position['ticket']}: {order_result.comment}")
        return None

    logger.info(f"Position {position['ticket']} closed successfully.")
    return order_result


def close_all_positions(order_type='all', magic=None, type_filling=mt5.ORDER_FILLING_IOC):
    order_type_dict = {
        'BUY': mt5.ORDER_TYPE_BUY,
        'SELL': mt5.ORDER_TYPE_SELL
    }

    if mt5.positions_total() > 0:
        positions = mt5.positions_get()
        if positions is None:
            logger.error("Failed to retrieve positions.")
            return []

        positions_data = [pos._asdict() for pos in positions]
        positions_df = pd.DataFrame(positions_data)

        # Filtering by magic if specified
        if magic is not None:
            positions_df = positions_df[positions_df['magic'] == magic]

        # Filtering by order_type if not 'all'
        if order_type != 'all':
            if order_type not in order_type_dict:
                logger.error(f"Invalid order_type: {order_type}. Must be 'BUY', 'SELL', or 'all'.")
                return []
            positions_df = positions_df[positions_df['type'] == order_type_dict[order_type]]

        if positions_df.empty:
            logger.error('No open positions matching the criteria.')
            return []

        results = []
        for _, position in positions_df.iterrows():
            order_result = close_position(position, type_filling=type_filling)
            if order_result:
                results.append(order_result)
            else:
                logger.error(f"Failed to close position {position['ticket']}.")
        
        return results
    else:
        logger.error("No open positions to close.")
        return []

def get_positions(magic=None):
    total_positions = mt5.positions_total()
    if total_positions is None:
        logger.error("Failed to get positions total.")
        return pd.DataFrame()

    if total_positions > 0:
        positions = mt5.positions_get()
        if positions is None:
            logger.error("Failed to retrieve positions.")
            return pd.DataFrame()

        positions_data = [pos._asdict() for pos in positions]
        positions_df = pd.DataFrame(positions_data)

        if magic is not None:
            positions_df = positions_df[positions_df['magic'] == magic]

        return positions_df
    else:
        return pd.DataFrame(columns=['ticket', 'time', 'time_msc', 'time_update', 'time_update_msc', 'type',
                                   'magic', 'identifier', 'reason', 'volume', 'price_open', 'sl', 'tp',
                                   'price_current', 'swap', 'profit', 'symbol', 'comment', 'external_id'])
    

def get_deal_from_ticket(ticket, from_date=None, to_date=None):
    if not isinstance(ticket, int):
        logger.error("Ticket must be an integer.")
        return None

    # Define default date range if not provided
    if from_date is None or to_date is None:
        to_date = datetime.now(mt5.TIMEZONE)
        from_date = to_date - timedelta(minutes=15)  # Adjust based on polling interval

    # Convert datetime to MT5 time (integer)
    from_timestamp = int(from_date.timestamp())
    to_timestamp = int(to_date.timestamp())

    # Retrieve deals using the specified date range and position
    deals = mt5.history_deals_get(from_timestamp, to_timestamp, position=ticket)
    if not deals:
        logger.error(f"No deal history found for position ticket {ticket} between {from_date} and {to_date}.")
        return None

    # Convert deals to a DataFrame for easier processing
    deals_df = pd.DataFrame([deal._asdict() for deal in deals])

    # Optional: Verify that all deals belong to the same symbol
    if not deals_df.empty and not all(deal == deals_df['symbol'].iloc[0] for deal in deals_df['symbol']):
        logger.error(f"Inconsistent symbols found in deals for position ticket {ticket}.")
        return None

    # Extract relevant information
    if not deals_df.empty:
        deal_details = {
            'ticket': ticket,
            'symbol': deals_df['symbol'].iloc[0],
            'type': 'BUY' if deals_df['type'].iloc[0] == 'DEAL_TYPE_BUY' else 'SELL',
            'volume': deals_df['volume'].sum(),
            'open_time': datetime.fromtimestamp(deals_df['time'].min(), tz=mt5.TIMEZONE),
            'close_time': datetime.fromtimestamp(deals_df['time'].max(), tz=mt5.TIMEZONE),
            'open_price': deals_df['price'].iloc[0],
            'close_price': deals_df['price'].iloc[-1],
            'profit': deals_df['profit'].sum(),
            'commission': deals_df['commission'].sum(),
            'swap': deals_df['swap'].sum(),
            'comment': deals_df['comment'].iloc[-1]  # Use the last comment if multiple
        }
        return deal_details
    else:
        return None


_RETCODE_MESSAGES = {
    getattr(mt5, 'TRADE_RETCODE_REQUOTE', 10004): "Requote.",
    getattr(mt5, 'TRADE_RETCODE_REJECT', 10006): "Request rejected by the trade server.",
    getattr(mt5, 'TRADE_RETCODE_CANCEL', 10007): "Request canceled by trader.",
    getattr(mt5, 'TRADE_RETCODE_PLACED', 10008): "Order placed.",
    getattr(mt5, 'TRADE_RETCODE_DONE', 10009): "Request completed.",
    getattr(mt5, 'TRADE_RETCODE_DONE_PARTIAL', 10010): "Request completed partially.",
    getattr(mt5, 'TRADE_RETCODE_ERROR', 10011): "Request processing error.",
    getattr(mt5, 'TRADE_RETCODE_TIMEOUT', 10012): "Request canceled by timeout.",
    getattr(mt5, 'TRADE_RETCODE_INVALID', 10013): "Invalid request.",
    getattr(mt5, 'TRADE_RETCODE_INVALID_VOLUME', 10014): "Invalid volume for the order.",
    getattr(mt5, 'TRADE_RETCODE_INVALID_PRICE', 10015): "Invalid price in the request.",
    getattr(mt5, 'TRADE_RETCODE_INVALID_STOPS', 10016): "Invalid SL/TP levels in the request.",
    getattr(mt5, 'TRADE_RETCODE_TRADE_DISABLED', 10017): "Trading is disabled for this account or symbol.",
    getattr(mt5, 'TRADE_RETCODE_MARKET_CLOSED', 10018): "Market is closed for this symbol.",
    getattr(mt5, 'TRADE_RETCODE_NO_MONEY', 10019): "Not enough money to complete the request.",
    getattr(mt5, 'TRADE_RETCODE_PRICE_CHANGED', 10020): "Price changed.",
    getattr(mt5, 'TRADE_RETCODE_PRICE_OFF', 10021): "No quotes to process the request.",
    getattr(mt5, 'TRADE_RETCODE_INVALID_EXPIRATION', 10022): "Invalid order expiration date in the request.",
    getattr(mt5, 'TRADE_RETCODE_ORDER_CHANGED', 10023): "Order state changed.",
    getattr(mt5, 'TRADE_RETCODE_TOO_MANY_REQUESTS', 10024): "Too many requests.",
    getattr(mt5, 'TRADE_RETCODE_NO_CHANGES', 10025): "No changes in request.",
    getattr(mt5, 'TRADE_RETCODE_SERVER_DISABLES_AT', 10026): "Autotrading disabled by server.",
    getattr(mt5, 'TRADE_RETCODE_CLIENT_DISABLES_AT', 10027): "Autotrading disabled by client terminal.",
    getattr(mt5, 'TRADE_RETCODE_LOCKED', 10028): "Request locked for processing.",
    getattr(mt5, 'TRADE_RETCODE_FROZEN', 10029): "Order or position frozen.",
    getattr(mt5, 'TRADE_RETCODE_INVALID_FILL', 10030): "Invalid order filling type.",
    getattr(mt5, 'TRADE_RETCODE_CONNECTION', 10031): "No connection with the trade server.",
    getattr(mt5, 'TRADE_RETCODE_ONLY_REAL', 10032): "Operation allowed only for live accounts.",
    getattr(mt5, 'TRADE_RETCODE_LIMIT_ORDERS', 10033): "Pending orders limit reached.",
    getattr(mt5, 'TRADE_RETCODE_LIMIT_VOLUME', 10034): "Volume limit for symbol/order type reached.",
    getattr(mt5, 'TRADE_RETCODE_INVALID_ORDER', 10035): "Invalid or prohibited order type.",
    getattr(mt5, 'TRADE_RETCODE_POSITION_CLOSED', 10036): "Position already closed.",
    getattr(mt5, 'TRADE_RETCODE_INVALID_CLOSE_VOLUME', 10038): "Invalid close volume.",
    getattr(mt5, 'TRADE_RETCODE_CLOSE_ORDER_EXIST', 10039): "Close order already exists for the position.",
    getattr(mt5, 'TRADE_RETCODE_LIMIT_POSITIONS', 10040): "Open positions/orders limit reached.",
    getattr(mt5, 'TRADE_RETCODE_REJECT_CANCEL', 10041): "Pending order activation rejected, order canceled.",
    getattr(mt5, 'TRADE_RETCODE_LONG_ONLY', 10042): "Only long positions allowed for this symbol.",
    getattr(mt5, 'TRADE_RETCODE_SHORT_ONLY', 10043): "Only short positions allowed for this symbol.",
    getattr(mt5, 'TRADE_RETCODE_CLOSE_ONLY', 10044): "Only position closing allowed for this symbol.",
    getattr(mt5, 'TRADE_RETCODE_FIFO_CLOSE', 10045): "Positions must be closed FIFO (First-In-First-Out).",
    getattr(mt5, 'TRADE_RETCODE_HEDGE_PROHIBITED', 10046): "Hedging prohibited; opposite positions not allowed.",
}

_ORDER_TYPE_ALIASES = {
    'BUY': 'ORDER_TYPE_BUY',
    'SELL': 'ORDER_TYPE_SELL',
}


def validate_order(symbol, order_type, volume, sl=None, tp=None,
                    deviation=20, magic=0, type_filling=None):
    """
    Dry-run a market order via mt5.order_check() without sending it.

    Args:
        symbol: Trading symbol, e.g. 'EURUSD'.
        order_type: 'BUY'/'SELL' (case-insensitive) or an mt5.ORDER_TYPE_* constant.
        volume: Order volume in lots.
        sl: Optional stop loss price.
        tp: Optional take profit price.
        deviation: Max price deviation in points (default 20).
        magic: Magic number to tag the request (default 0).
        type_filling: Optional mt5.ORDER_FILLING_* constant; defaults to ORDER_FILLING_IOC.

    Returns:
        dict with keys: ok, retcode, comment, margin_required, free_margin_after, raw_result.
        No order is sent; this only calls mt5.order_check().
    """
    result_template = {
        "ok": False,
        "retcode": None,
        "comment": None,
        "margin_required": None,
        "free_margin_after": None,
        "raw_result": None,
    }

    # Resolve order type (accept 'BUY'/'SELL' strings or raw mt5 constants)
    if isinstance(order_type, str):
        alias = _ORDER_TYPE_ALIASES.get(order_type.upper())
        if alias is None:
            logger.error(f"validate_order: invalid order_type '{order_type}'. Expected 'BUY' or 'SELL'.")
            result_template["comment"] = f"Invalid order_type: '{order_type}'. Expected 'BUY' or 'SELL'."
            return result_template
        resolved_type = getattr(mt5, alias)
    else:
        resolved_type = order_type

    logger.info(
        f"validate_order: checking symbol={symbol} order_type={order_type} "
        f"volume={volume} sl={sl} tp={tp}"
    )

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        error_code, error_str = mt5.last_error()
        logger.error(f"validate_order: unknown symbol '{symbol}' ({error_str}).")
        result_template["comment"] = f"Unknown symbol: '{symbol}' ({error_str})."
        return result_template

    if not symbol_info.visible:
        if not mt5.symbol_select(symbol, True):
            error_code, error_str = mt5.last_error()
            logger.error(f"validate_order: could not select symbol '{symbol}' ({error_str}).")
            result_template["comment"] = f"Symbol '{symbol}' not visible/selectable ({error_str})."
            return result_template

    tick = mt5.symbol_info_tick(symbol)
    if tick is None or (tick.bid == 0.0 and tick.ask == 0.0):
        error_code, error_str = mt5.last_error()
        logger.error(f"validate_order: failed to get tick data for '{symbol}' ({error_str}).")
        result_template["comment"] = f"No tick data available for '{symbol}' ({error_str})."
        return result_template

    if resolved_type == mt5.ORDER_TYPE_BUY:
        price = tick.ask
    elif resolved_type == mt5.ORDER_TYPE_SELL:
        price = tick.bid
    else:
        logger.error(f"validate_order: unsupported order_type '{order_type}' for a market order check.")
        result_template["comment"] = f"Unsupported order_type for market order: '{order_type}'."
        return result_template

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(volume),
        "type": resolved_type,
        "price": price,
        "deviation": deviation,
        "magic": magic,
        "comment": "validate_order dry-run",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": type_filling if type_filling is not None else mt5.ORDER_FILLING_IOC,
    }
    if sl is not None:
        request["sl"] = sl
    if tp is not None:
        request["tp"] = tp

    logger.info(f"validate_order: order_check request={request}")

    check_result = mt5.order_check(request)
    if check_result is None:
        error_code, error_str = mt5.last_error()
        logger.error(f"validate_order: order_check() returned None ({error_str}).")
        result_template["comment"] = f"order_check() failed to return a result ({error_str})."
        return result_template

    result_dict = check_result._asdict()
    retcode = result_dict.get("retcode")
    ok = retcode == mt5.TRADE_RETCODE_DONE

    readable_comment = _RETCODE_MESSAGES.get(retcode, result_dict.get("comment"))
    outcome = {
        "ok": ok,
        "retcode": retcode,
        "comment": readable_comment,
        "margin_required": result_dict.get("margin"),
        "free_margin_after": result_dict.get("margin_free"),
        "raw_result": result_dict,
    }

    logger.info(
        f"validate_order: result ok={outcome['ok']} retcode={outcome['retcode']} "
        f"comment='{outcome['comment']}' margin_required={outcome['margin_required']} "
        f"free_margin_after={outcome['free_margin_after']}"
    )

    return outcome


def get_order_from_ticket(ticket):
    if not isinstance(ticket, int):
        logger.error("Ticket must be an integer.")
        return None

    # Get the order history
    order = mt5.history_orders_get(ticket=ticket)
    if order is None or len(order) == 0:
        logger.error(f"No order history found for ticket {ticket}")
        return None

    # Convert order to a dictionary
    order_dict = order[0]._asdict()

    return order_dict
