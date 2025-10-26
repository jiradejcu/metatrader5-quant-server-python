import json
import logging
from decimal import Decimal
from app.connectors.binance.api.order import new_order
from app.connectors.binance.api.position import get_position
from app.connectors.binance.api.ticker import get_ticker

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
        position_data = get_position(symbol)
        logger.info(f"Fetched position data for {symbol}: {position_data}")

        if position_data is not None:
            current_position_amt = Decimal(position_data.get('positionAmt', '0'))
        else:
            logger.warning(f"Could not find position data for {symbol} in Redis.")
            current_position_amt = Decimal('0')
        
        ticker_data = get_ticker(symbol)
        price = ticker_data['best_bid'] if side == 'BUY' else ticker_data['best_ask']

        if not price:
            logger.warning(f"Could not find ticker price for {symbol} in Redis. Skipping.")
            return

        logger.info(f"Arbitrage entry:\nCurrent position for {symbol} is {current_position_amt}.\nTarget is {TARGET_POSITION_SIZE}.\nPlacing {side} order at price {price}.")

        if current_position_amt < TARGET_POSITION_SIZE:
            new_order(symbol=symbol, quantity=0.002, price=price, side=side)
        else:
            logger.info(f"Position size {current_position_amt} for {symbol} is already at or above target. No action taken.")

    except Exception as e:
        logger.error(f"Error in arbitrage entry algorithm for {symbol}: {e}", exc_info=True)
