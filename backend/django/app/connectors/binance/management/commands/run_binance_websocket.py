import os
import logging
import time
import json
from dotenv import load_dotenv
from django.core.management.base import BaseCommand
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

load_dotenv()
api_key = os.environ.get('API_KEY_BINANCE')
api_secret = os.environ.get('API_SECRET_BINANCE')

logger = logging.getLogger(__name__)

def message_handler(_, message):
    """
    General message handler that routes messages to specific handlers
    based on the stream name.
    """
    try:
        data = json.loads(message)
        stream = data.get('stream')
        payload = data.get('data', {})

        if not stream:
            logger.warning(f"Received message without a stream name: {message}")
            return

        if '@depth' in stream:
            handle_orderbook_message(payload)
        elif '@trade' in stream:
            handle_trade_message(payload)
        else:
            logger.info(f"Received message from unhandled stream '{stream}'")

    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON message: {message}")
    except Exception as e:
        logger.error(f"An unexpected error occurred in message_handler: {e}")


def handle_orderbook_message(data):
    """Handles and logs incoming order book (depth) messages."""
    symbol = data.get('s', 'UNKNOWN')
    best_bid = data.get('b', [['']])[0][0]
    best_ask = data.get('a', [['']])[0][0]
    logger.info(f"[{symbol:^10}] ORDER BOOK | Best Bid: {best_bid:<15} Best Ask: {best_ask}")


def handle_trade_message(data):
    """Handles and logs incoming trade messages."""
    symbol = data.get('s', 'UNKNOWN')
    price = data.get('p')
    quantity = data.get('q')
    side = "SELL" if data.get('m', False) else "BUY"
    logger.info(f"[{symbol:^10}] NEW TRADE  | Side: {side:<4}  Price: {price:<15} Quantity: {quantity}")


class Command(BaseCommand):
    help = 'Connects to Binance USD-M Futures WebSocket and subscribes to order book and trade streams for given symbols.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbol',
            nargs='+',
            type=str,
            required=True,
            help='One or more trading symbols to subscribe to (e.g., btcusdt ethusdt).',
        )

    def handle(self, *args, **options):
        symbols = [s.lower() for s in options['symbol']]
        self.stdout.write(self.style.SUCCESS(f"Connecting to Binance WebSocket for symbols: {', '.join(symbols)}"))

        client = UMFuturesWebsocketClient(on_message=message_handler)

        # Subscribe to multiple streams: order book (diff_book_depth) and trades (trade)
        streams = []
        for symbol in symbols:
            streams.append(f"{symbol}@depth")
            streams.append(f"{symbol}@trade")

        client.subscribe(stream=streams)
        self.stdout.write(self.style.SUCCESS(f"Successfully subscribed to streams: {', '.join(streams)}"))
        self.stdout.write("Receiving updates... Press CTRL+C to stop.")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nKeyboard Interrupt received. Closing WebSocket connection."))
            client.stop()
            self.stdout.write(self.style.SUCCESS("Connection closed."))
