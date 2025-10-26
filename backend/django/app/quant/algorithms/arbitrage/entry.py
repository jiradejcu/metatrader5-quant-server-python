import logging
from decimal import Decimal
import json
from app.connectors.binance.api.order import new_order
from app.utils.redis_client import get_redis_connection

logger = logging.getLogger(__name__)

TARGET_POSITION_SIZE = Decimal('0.002')

def arbitrage_entry_algorithm(alert_data: dict):
    """
    Analyzes an arbitrage opportunity from an alert and places a Binance order
    if the current position size is below a specific threshold.
    """
    side = None

    if alert_data.get('condition') == 'Crossing Down' and alert_data.get('threshold') <= -0.2:
            side = 'BUY'
    elif alert_data.get('condition') == 'Crossing Up' and alert_data.get('threshold') >= 0.2:
            side = 'SELL'

    if side is None:
        logger.info("Arbitrage entry: No valid crossing condition met.")
        return

    symbol = alert_data.get('symbol')
    if not symbol:
        logger.error("Arbitrage entry: 'symbol' not found in alert data.")
        return

    try:
        redis_conn = get_redis_connection()

        # Get current position size from Redis
        position_data_raw = redis_conn.get(f"position:{symbol}")
        current_position_amt = None
        if position_data_raw:
            position_data = json.loads(position_data_raw)
            current_position_amt = Decimal(position_data.get('positionAmt'))
        else:
            logger.warning(f"Could not find position data for {symbol} in Redis.")
            current_position_amt = Decimal('0')

        # Get latest price from Redis
        ticker_data = redis_conn.hgetall(f"ticker:{symbol}")
        price = ticker_data.get(b'best_bid') if side == 'BUY' else ticker_data.get(b'best_ask')

        if not price:
            logger.warning(f"Could not find ticker price for {symbol} in Redis. Skipping.")
            return

        if current_position_amt < TARGET_POSITION_SIZE:
            new_order(symbol=symbol, quantity=0.002, price=price.decode('utf-8'), side=side)
        else:
            logger.info(f"Position size {current_position_amt} for {symbol} is already at or above target. No action taken.")

    except Exception as e:
        logger.error(f"Error in arbitrage entry algorithm for {symbol}: {e}", exc_info=True)
