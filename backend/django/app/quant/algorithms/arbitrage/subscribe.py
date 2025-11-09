import logging
import asyncio
import threading
import os
from . import config
import app.connectors.binance.api.ticker as ticker_stream
import app.connectors.binance.api.position as position_stream

logger = logging.getLogger(__name__)

def start_subscriptions():
    if os.environ.get('RUN_MAIN') != 'true':
        return

    symbol = config.PAIRS[0]['binance']
    logger.info(f"Starting arbitrage subscription tasks for {symbol}...")
    try:
        threading.Thread(target=asyncio.run, args=(ticker_stream.subscribe_symbol_ticker(symbol),), daemon=True).start()
        threading.Thread(target=asyncio.run, args=(position_stream.subscribe_position_information(symbol),), daemon=True).start()
        logger.info(f"Successfully started subscription threads for {symbol}.")
    except Exception as e:
        logger.error(f"Error in arbitrage subscribe tasks for {symbol}: {e}", exc_info=True)