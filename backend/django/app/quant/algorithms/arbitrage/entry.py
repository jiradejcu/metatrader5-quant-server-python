import logging
from decimal import Decimal
from app.connectors.binance.api.order import new_order

logger = logging.getLogger(__name__)

TARGET_POSITION_SIZE = Decimal('1.00')

def arbitrage_entry_algorithm(alert_data: dict):
    """
    Analyzes an arbitrage opportunity from an alert and places a Binance order
    if the current position size is below a specific threshold.
    """
    symbol = alert_data.get('symbol')
    side = alert_data.get('side', 'BUY').upper()
    current_position = 0

    if not symbol:
        logger.error("Arbitrage entry: 'symbol' not found in alert data.")
        return

    try:
        if current_position < TARGET_POSITION_SIZE:
            new_order()
        else:
            logger.info(f"Position size for {symbol} is already at or above target. No action taken.")

    except Exception as e:
        logger.error(f"Error in arbitrage entry algorithm for {symbol}: {e}", exc_info=True)
