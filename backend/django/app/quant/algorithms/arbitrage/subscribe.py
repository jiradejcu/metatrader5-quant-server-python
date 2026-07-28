import logging
import asyncio
import threading
import os
from . import config
from app.utils.api.positions import subscribe_hedge_position

logger = logging.getLogger(__name__)


def _get_position_stream(exchange: str):
    """Return the connector position module for the given primary exchange.

    Mirrors the exchange dispatch in QuantConfig.ready() so a pair can name any
    supported primary exchange and the matching connector publishes position
    updates to the position:{exchange}:{symbol} Redis channel that
    position_sync subscribes to. Imported lazily so only the selected
    exchange's SDK is initialised.
    """
    if exchange == 'binance':
        import app.connectors.binance.api.position as position_stream
    elif exchange == 'bybit':
        import app.connectors.bybit.api.position as position_stream
    elif exchange == 'hyperliquid':
        import app.connectors.hyperliquid.api.position as position_stream
    else:
        raise ValueError(f"Unsupported primary exchange: {exchange}")
    return position_stream


def start_subscriptions():
    if os.environ.get('RUN_MAIN') != 'true':
        return

    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    primary_exchange = config.PAIRS[PAIR_INDEX]['primary']['exchange']
    primary_symbol = config.PAIRS[PAIR_INDEX]['primary']['symbol']
    hedge_symbol = config.PAIRS[PAIR_INDEX]['hedge']['symbol']
    logger.info(f"Starting arbitrage subscription tasks for {primary_symbol}...")
    try:
        position_stream = _get_position_stream(primary_exchange)
        threading.Thread(target=asyncio.run, args=(position_stream.subscribe_position_information(primary_symbol),), daemon=True).start()
        threading.Thread(target=asyncio.run, args=(subscribe_hedge_position(hedge_symbol),), daemon=True).start()
        logger.info(f"Successfully started subscription threads for {primary_symbol}.")
    except Exception as e:
        logger.error(f"Error in arbitrage subscribe tasks for {primary_symbol}: {e}", exc_info=True)
