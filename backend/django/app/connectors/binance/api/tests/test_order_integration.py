"""
Integration tests — hit the real Binance Futures API.

Run with:
    pytest backend/django/app/connectors/binance/api/tests/test_order_integration.py -v -s

Requires API_KEY_BINANCE and API_SECRET_BINANCE in the environment (or .env).
Orders are placed far from market and cancelled in teardown so they never fill.
"""
import os
import sys
import time
import pytest
from dotenv import load_dotenv

load_dotenv()

# Skip entire module if keys are absent
pytestmark = pytest.mark.skipif(
    not os.environ.get("API_KEY_BINANCE"),
    reason="API_KEY_BINANCE not set",
)

from app.connectors.binance.api.order import new_order, cancel_all_open_orders, chase_order

SYMBOL = "XAUUSDT"
QUANTITY = 0.01
# Far below market (~4750) so a GTX BUY will never fill
SAFE_BUY_PRICE = "3000"


@pytest.fixture(autouse=True)
def cleanup():
    """Cancel all open orders before and after each test."""
    cancel_all_open_orders(SYMBOL)
    yield
    cancel_all_open_orders(SYMBOL)


class TestChaseOrderIntegration:

    def test_new_order_then_chase_modify(self):
        """Place a real BUY limit order, then chase (modify) it. Verifies price=None + price_match=QUEUE works."""
        # 1. Place a limit GTX order far below market so it parks in the book
        placed = new_order(
            symbol=SYMBOL,
            quantity=QUANTITY,
            price=SAFE_BUY_PRICE,
            side="BUY",
        )
        assert placed is not None, "new_order returned None — check API keys or symbol"
        order_id = getattr(placed, "order_id", None) or placed.get("orderId")
        assert order_id, f"No order_id in response: {placed}"

        # Small pause so the order is visible in get_open_orders
        time.sleep(1.0)

        # 2. Chase (modify) — this is the path that was broken
        result = chase_order(symbol=SYMBOL, quantity=QUANTITY, side="BUY")

        assert result is not None, (
            "chase_order returned None — modify_order likely failed. "
            "Check logs for the actual error."
        )

        modified_id = getattr(result, "order_id", None) or result.get("orderId")
        assert modified_id == order_id, (
            f"Modified order_id {modified_id} doesn't match original {order_id}"
        )
