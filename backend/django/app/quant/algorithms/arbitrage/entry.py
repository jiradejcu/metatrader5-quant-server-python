import logging
from decimal import Decimal
import json
from app.connectors.binance.api.order import new_order
from app.connectors.redis_client import get_redis_connection

logger = logging.getLogger(__name__)

TARGET_POSITION_SIZE = Decimal('1.00')

def arbitrage_entry_algorithm(alert_data: dict):
    """
    Analyzes an arbitrage opportunity from an alert and places a Binance order
    if the current position size is below a specific threshold.
    """
    symbol = alert_data.get('symbol')
    side = alert_data.get('side', 'BUY').upper()

    if not symbol:
        logger.error("Arbitrage entry: 'symbol' not found in alert data.")
        return

    try:
        redis_conn = get_redis_connection()

        # Get current position size from Redis
        position_data_raw = redis_conn.get(f"position:{symbol}")
        current_position_amt = Decimal('0')
        if position_data_raw:
            position_data = json.loads(position_data_raw)
            current_position_amt = Decimal(position_data.get('positionAmt', '0'))

        # Get latest price from Redis
        ticker_data = redis_conn.hgetall(f"ticker:{symbol}")
        price_to_buy = ticker_data.get(b'best_ask') # Buy at the ask price

        if not price_to_buy:
            logger.warning(f"Could not find ticker price for {symbol} in Redis. Skipping.")
            return

        if current_position < TARGET_POSITION_SIZE:
            new_order(symbol=symbol, quantity=0.002, price=price_to_buy.decode('utf-8'), side=side)
        else:
            logger.info(f"Position size for {symbol} is already at or above target. No action taken.")

    except Exception as e:
        logger.error(f"Error in arbitrage entry algorithm for {symbol}: {e}", exc_info=True)
