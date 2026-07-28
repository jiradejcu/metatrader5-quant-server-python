import os
import logging
from dotenv import load_dotenv

from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    ConfigurationRestAPI,
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
)

load_dotenv()
logger = logging.getLogger(__name__)

configuration_rest_api = ConfigurationRestAPI(
    api_key=os.environ.get('API_KEY_BINANCE'),
    api_secret=os.environ.get('API_SECRET_BINANCE'),
    base_path=os.getenv(
        "BASE_PATH", DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL
    ),
)

client = DerivativesTradingUsdsFutures(config_rest_api=configuration_rest_api)


def get_order_book(symbol, limit=50):
    """Fetch current order book depth directly from the REST API.

    Returns {"bids": [(price, qty), ...], "asks": [(price, qty), ...]}, each
    sorted best-to-worst (bids descending, asks ascending), or None on error.
    Polled on demand rather than streamed — callers only need a depth snapshot
    at decision time (e.g. right before closing a position).
    """
    try:
        response = client.rest_api.order_book(symbol=symbol, limit=limit)
        data = response.data()
        bids = [(float(p), float(q)) for p, q in (data.bids or [])]
        asks = [(float(p), float(q)) for p, q in (data.asks or [])]
        return {"bids": bids, "asks": asks}
    except Exception as e:
        logger.error(f"Get order book error for {symbol}: {e}")
        return None
