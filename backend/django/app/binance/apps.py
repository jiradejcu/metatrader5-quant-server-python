import os
import logging
import time
import json
from dotenv import load_dotenv
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

load_dotenv()
api_key = os.environ.get('API_KEY_BINANCE')
api_secret = os.environ.get('API_SECRET_BINANCE')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def orderbook_message_handler(_, message):
    """
    Handles and processes incoming WebSocket orderbook (depth) messages,
    extracting and printing the best bid and best ask.
    """
    try:
        data = json.loads(message)
        bids = data.get('b')
        asks = data.get('a')

        best_bid_price = None
        best_ask_price = None
        
        if bids and len(bids) > 0:
            best_bid_price = bids[0][0]

        if asks and len(asks) > 0:
            best_ask_price = asks[0][0]

        if best_bid_price or best_ask_price:
            logging.info(
                f"[{data.get('s', 'UNKNOWN')}] "
                f"Best BID: {best_bid_price:<15} "
                f"Best ASK: {best_ask_price}"
            )

    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON message: {message}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    SYMBOL = "paxgusdt" 

    logging.info(f"Connecting to Binance USDⓈ-M Futures WebSocket for {SYMBOL}...")
    
    client = UMFuturesWebsocketClient(on_message=orderbook_message_handler)
    client.diff_book_depth(symbol=SYMBOL) 
    
    logging.info(f"Subscribed to {SYMBOL} orderbook. Receiving updates (Best Bid/Ask) every 250ms...")

    try:
        while True:
            time.sleep(1) 
    except KeyboardInterrupt:
        logging.info("Keyboard Interrupt received. Closing WebSocket connection.")
        client.stop()