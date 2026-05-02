import logging
import asyncio
import threading
import os
from . import config
import app.connectors.binance.api.ticker as ticker_stream
import app.connectors.binance.api.position as position_stream
from app.utils.api.positions import subscribe_hedge_position

logger = logging.getLogger(__name__)

def start_subscriptions():
    if os.environ.get('RUN_MAIN') != 'true':
        return

    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    entry_symbol = config.PAIRS[PAIR_INDEX]['entry']['symbol']
    hedge_symbol = config.PAIRS[PAIR_INDEX]['hedge']['symbol']
    logger.info(f"Starting arbitrage subscription tasks for {entry_symbol}...")
    try:
        threading.Thread(target=asyncio.run, args=(position_stream.subscribe_position_information(entry_symbol),), daemon=True).start()
        threading.Thread(target=asyncio.run, args=(subscribe_hedge_position(hedge_symbol),), daemon=True).start()
        logger.info(f"Successfully started subscription threads for {entry_symbol}.")
    except Exception as e:
        logger.error(f"Error in arbitrage subscribe tasks for {entry_symbol}: {e}", exc_info=True)