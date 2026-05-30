from enum import Enum
from typing import List, Dict, Callable, Optional
from dataclasses import dataclass, field
from datetime import timezone, timedelta
import pytz

LOCAL_TZ = timezone(timedelta(hours=7))

from enum import Enum

class MT5Timeframe(Enum):
    M1 = 'M1'      # 1-minute
    M5 = 'M5'       # 5-minute
    M15 = 'M15'     # 15-minute
    M30 = 'M30'     # 30-minute
    H1 = 'H1'       # 1-hour
    H4 = 'H4'       # 4-hour
    D1 = 'D1'       # daily
    W1 = 'W1'       # weekly
    MN1 = 'MN1'     # monthly

class RETCODES(Enum):
    TRADE_RETCODE_REQUOTE= 'TRADE_RETCODE_REQUOTE',
    TRADE_RETCODE_REJECT= "TRADE_RETCODE_REJECT",
    TRADE_RETCODE_CANCEL= "TRADE_RETCODE_CANCEL",
    TRADE_RETCODE_PLACED= "TRADE_RETCODE_PLACED",
    TRADE_RETCODE_DONE= "TRADE_RETCODE_DONE",
    TRADE_RETCODE_DONE_PARTIAL= "TRADE_RETCODE_DONE_PARTIAL",
    TRADE_RETCODE_ERROR= "TRADE_RETCODE_ERROR",
    TRADE_RETCODE_TIMEOUT= "TRADE_RETCODE_TIMEOUT",
    TRADE_RETCODE_INVALID= "TRADE_RETCODE_INVALID",
    TRADE_RETCODE_INVALID_VOLUME= "TRADE_RETCODE_INVALID_VOLUME",
    TRADE_RETCODE_INVALID_PRICE= "TRADE_RETCODE_INVALID_PRICE",
    TRADE_RETCODE_INVALID_STOPS= "TRADE_RETCODE_INVALID_STOPS",
    TRADE_RETCODE_TRADE_DISABLED= "TRADE_RETCODE_TRADE_DISABLED",
    TRADE_RETCODE_MARKET_CLOSED= "TRADE_RETCODE_MARKET_CLOSED",
    TRADE_RETCODE_NO_MONEY= "TRADE_RETCODE_NO_MONEY",
    TRADE_RETCODE_PRICE_CHANGED= "TRADE_RETCODE_PRICE_CHANGED",
    TRADE_RETCODE_PRICE_OFF= "TRADE_RETCODE_PRICE_OFF",
    TRADE_RETCODE_INVALID_EXPIRATION= "TRADE_RETCODE_INVALID_EXPIRATION",
    TRADE_RETCODE_ORDER_CHANGED= "TRADE_RETCODE_ORDER_CHANGED",
    TRADE_RETCODE_TOO_MANY_REQUESTS= "TRADE_RETCODE_TOO_MANY_REQUESTS",
    TRADE_RETCODE_NO_CHANGES= "TRADE_RETCODE_NO_CHANGES",
    TRADE_RETCODE_SERVER_DISABLES_AT= "TRADE_RETCODE_SERVER_DISABLES_AT",
    TRADE_RETCODE_CLIENT_DISABLES_AT= "TRADE_RETCODE_CLIENT_DISABLES_AT",
    TRADE_RETCODE_LOCKED= "TRADE_RETCODE_LOCKED",
    TRADE_RETCODE_FROZEN= "TRADE_RETCODE_FROZEN",
    TRADE_RETCODE_INVALID_FILL= "TRADE_RETCODE_INVALID_FILL",
    TRADE_RETCODE_CONNECTION= "TRADE_RETCODE_CONNECTION",
    TRADE_RETCODE_ONLY_REAL= "TRADE_RETCODE_ONLY_REAL",
    TRADE_RETCODE_LIMIT_ORDERS= "TRADE_RETCODE_LIMIT_ORDERS",
    TRADE_RETCODE_LIMIT_VOLUME= "TRADE_RETCODE_LIMIT_VOLUME",
    TRADE_RETCODE_INVALID_ORDER= "TRADE_RETCODE_INVALID_ORDER",
    TRADE_RETCODE_POSITION_CLOSED= "TRADE_RETCODE_POSITION_CLOSED",
    TRADE_RETCODE_INVALID_CLOSE_VOLUME= "TRADE_RETCODE_INVALID_CLOSE_VOLUME",
    TRADE_RETCODE_CLOSE_ORDER_EXIST= "TRADE_RETCODE_CLOSE_ORDER_EXIST",
    TRADE_RETCODE_LIMIT_POSITIONS= "TRADE_RETCODE_LIMIT_POSITIONS",
    TRADE_RETCODE_REJECT_CANCEL= "TRADE_RETCODE_REJECT_CANCEL",
    TRADE_RETCODE_LONG_ONLY= "TRADE_RETCODE_LONG_ONLY",
    TRADE_RETCODE_SHORT_ONLY= "TRADE_RETCODE_SHORT_ONLY",
    TRADE_RETCODE_CLOSE_ONLY= "TRADE_RETCODE_CLOSE_ONLY",
    TRADE_RETCODE_FIFO_CLOSE= "TRADE_RETCODE_FIFO_CLOSE"

class RETCODE_DESCRIPTIONS(Enum):
    TRADE_RETCODE_REQUOTE= "Requote",
    TRADE_RETCODE_REJECT= "Request rejected",
    TRADE_RETCODE_CANCEL= "Request canceled by trader",
    TRADE_RETCODE_PLACED= "Order placed",
    TRADE_RETCODE_DONE= "Request completed",
    TRADE_RETCODE_DONE_PARTIAL= "Only part of the request was completed",
    TRADE_RETCODE_ERROR= "Request processing error",
    TRADE_RETCODE_TIMEOUT= "Request canceled by timeout",
    TRADE_RETCODE_INVALID= "Invalid request",
    TRADE_RETCODE_INVALID_VOLUME= "Invalid volume in the request",
    TRADE_RETCODE_INVALID_PRICE= "Invalid price in the request",
    TRADE_RETCODE_INVALID_STOPS= "Invalid stops in the request",
    TRADE_RETCODE_TRADE_DISABLED= "Trade is disabled",
    TRADE_RETCODE_MARKET_CLOSED= "Market is closed",
    TRADE_RETCODE_NO_MONEY= "There is not enough money to complete the request",
    TRADE_RETCODE_PRICE_CHANGED= "Prices changed",
    TRADE_RETCODE_PRICE_OFF= "There are no quotes to process the request",
    TRADE_RETCODE_INVALID_EXPIRATION= "Invalid order expiration date in the request",
    TRADE_RETCODE_ORDER_CHANGED= "Order state changed",
    TRADE_RETCODE_TOO_MANY_REQUESTS= "Too frequent requests",
    TRADE_RETCODE_NO_CHANGES= "No changes in request",
    TRADE_RETCODE_SERVER_DISABLES_AT= "Autotrading disabled by server",
    TRADE_RETCODE_CLIENT_DISABLES_AT= "Autotrading disabled by client terminal",
    TRADE_RETCODE_LOCKED= "Request locked for processing",
    TRADE_RETCODE_FROZEN= "Order or position frozen",
    TRADE_RETCODE_INVALID_FILL= "Invalid order filling type",
    TRADE_RETCODE_CONNECTION= "No connection with the trade server",
    TRADE_RETCODE_ONLY_REAL= "Operation is allowed only for live accounts",
    TRADE_RETCODE_LIMIT_ORDERS= "The number of pending orders has reached the limit",
    TRADE_RETCODE_LIMIT_VOLUME= "The volume of orders and positions for the symbol has reached the limit",
    TRADE_RETCODE_INVALID_ORDER= "Incorrect or prohibited order type",
    TRADE_RETCODE_POSITION_CLOSED= "Position with the specified POSITION_IDENTIFIER has already been closed",
    TRADE_RETCODE_INVALID_CLOSE_VOLUME= "A close volume exceeds the current position volume",
    TRADE_RETCODE_CLOSE_ORDER_EXIST= "A close order already exists for a specified position",
    TRADE_RETCODE_LIMIT_POSITIONS= "The number of open positions simultaneously present on an account can be limited by the server settings",
    TRADE_RETCODE_REJECT_CANCEL= "The pending order activation request is rejected, the order is canceled",
    TRADE_RETCODE_LONG_ONLY= "The request is rejected, because the 'Only long positions are allowed' rule is set for the symbol",
    TRADE_RETCODE_SHORT_ONLY= "The request is rejected, because the 'Only short positions are allowed' rule is set for the symbol",
    TRADE_RETCODE_CLOSE_ONLY= "The request is rejected, because the 'Only position closing is allowed' rule is set for the symbol",
    TRADE_RETCODE_FIFO_CLOSE= "The request is rejected, because 'Position closing is allowed only by FIFO rule' flag is set for the trading account",

TIMEZONE = pytz.timezone('UTC')
METALS = ['XAUUSD', 'XAGUSD']
OILS = ['BRN', 'NG', 'WTI']
CRYPTOCURRENCIES = ['BITCOIN', 'ETHEREUM', 'SOLANA', 'DOGECOIN', 'LITECOIN', 'RIPPLE', 'BNB', 'UNISWAP', 'AVALANCH', 'CARDANO', 'CHAINLINK', 'POLKADOT', 'POLYGON', 'COSMOS', 'AXS']
CURRENCY_PAIRS: List[str] = ['USDJPY','USDCHF','USDCAD','EURUSD','EURGBP','EURJPY','EURCHF','EURCAD','EURAUD','EURNZD','GBPUSD','GBPJPY','GBPCHF','GBPCAD','GBPAUD','GBPNZD','CHFJPY','CADJPY','CADCHF','AUDUSD','AUDJPY','AUDCHF','AUDCAD','AUDNZD','NZDUSD','NZDJPY','NZDCHF','NZDCAD']
CURRENCIES: List[str] = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"]