"""
Automated tests for grid_bot trading logic.

Price data is injected via make_price_message() / make_grid_message() helpers
that produce the same dict shape the Redis pubsub delivers, letting you
reproduce any scenario without a live Redis instance.

External Binance calls (get_open_orders, get_ticker, get_position, new_order,
cancel_all_open_orders, chase_order) are patched on the loaded module object.
"""
import json
import sys
import types
import threading
import importlib.util
import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

# ---------------------------------------------------------------------------
# Load grid_bot.py under a synthetic parent package so that relative imports
# ("from . import config", "from . import state") resolve without needing
# the full Django app stack.
# ---------------------------------------------------------------------------

_PKG = "_gb_test_pkg"

_parent = types.ModuleType(_PKG)
_parent.__path__ = []
sys.modules[_PKG] = _parent

# --- minimal config stub ---
_config_mod = types.ModuleType(f"{_PKG}.config")
_config_mod.PAIRS = [
    {
        "entry": {"exchange": "binance", "symbol": "XAUUSDT"},
        "hedge": {"symbol": "XAUUSD"},
        "contract_size": 100,
        "minimum_trade_amount": 1,
    }
]
sys.modules[f"{_PKG}.config"] = _config_mod

# --- minimal state stub (mirrors the real state.py) ---
_state_mod = types.ModuleType(f"{_PKG}.state")
_state_mod.state_lock = threading.Lock()
_state_mod.placing_order_state = {
    "order_id": None, "status": None, "is_clean": True,
    "fill_pct": 0, "side": None, "price": None, "orig_qty": 0, "total_orders": 0,
}
sys.modules[f"{_PKG}.state"] = _state_mod

# --- load grid_bot.py as _PKG.grid_bot ---
_gb_path = pathlib.Path(__file__).parent.parent / "grid_bot.py"
_spec = importlib.util.spec_from_file_location(f"{_PKG}.grid_bot", str(_gb_path))
_gb = importlib.util.module_from_spec(_spec)
_gb.__package__ = _PKG
sys.modules[f"{_PKG}.grid_bot"] = _gb
_spec.loader.exec_module(_gb)

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

SYMBOL = "XAUUSDT"
CONTRACT_SIZE = 100
MIN_TRADE = 1
BOUNDARY = 500.0   # matches grid_bot.boundary_price default

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _order_snapshot(status="FILLED", side="BUY", order_id=None,
                    price=0.0, orig_qty=0, total_orders=0):
    return {
        "order_id": order_id,
        "status": status,
        "fill_pct": 0,
        "side": side,
        "is_clean": True,
        "price": price,
        "orig_qty": orig_qty,
        "total_orders": total_orders,
    }


def _open_order(side="BUY", price=2000.0, orig_qty=1.0):
    return SimpleNamespace(side=side, price=price, orig_qty=orig_qty)


def _ticker(bid=2000.0, ask=2001.0):
    return {"best_bid": str(bid), "best_ask": str(ask)}


def _position(amt=0.0):
    return {"positionAmt": str(amt)}


def make_price_message(channel: str, upper_diff: float, lower_diff: float) -> dict:
    """Return a dict shaped like a Redis pubsub price-diff message."""
    return {
        "type": "message",
        "channel": channel.encode(),
        "data": json.dumps({
            "current_upper_diff": upper_diff,
            "current_lower_diff": lower_diff,
        }).encode(),
    }


def make_grid_message(channel: str, upper_diff: float, lower_diff: float,
                      max_position_size: float, order_size: float) -> dict:
    """Return a dict shaped like a Redis pubsub grid-settings message."""
    return {
        "type": "message",
        "channel": channel.encode(),
        "data": json.dumps({
            "upper_diff": upper_diff,
            "lower_diff": lower_diff,
            "max_position_size": max_position_size,
            "order_size": order_size,
        }).encode(),
    }


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_globals():
    """Reset module-level state between tests."""
    _gb.optimistic_dirty_time = 0
    _gb.last_acted_order_id = None
    _gb.latest_upper = None
    _gb.latest_lower = None
    _gb.latest_grid_settings = None
    yield


# ---------------------------------------------------------------------------
# _parse_grid_settings
# ---------------------------------------------------------------------------

class TestParseGridSettings:

    def test_parses_all_fields(self):
        result = _gb._parse_grid_settings({
            "upper_diff": "10.5",
            "lower_diff": "-10.5",
            "max_position_size": "5.0",
            "order_size": "1.0",
        })
        assert result == {
            "upper": 10.5, "lower": -10.5,
            "max_position_size": 5.0, "order_size": 1.0,
        }

    def test_defaults_to_zero_on_missing_keys(self):
        result = _gb._parse_grid_settings({})
        assert result == {"upper": 0.0, "lower": 0.0, "max_position_size": 0.0, "order_size": 0.0}


# ---------------------------------------------------------------------------
# _execute_zone
# ---------------------------------------------------------------------------

class TestExecuteZone:

    def test_negative_capacity_cancels_all(self):
        with patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._execute_zone(SYMBOL, "SELL", "BUY", 2000.0, 1.0,
                              2000.0, 1.0, remaining_capacity=-0.5,
                              allow_chase=False, can_open=False)
        mock_cancel.assert_called_once_with(SYMBOL)

    def test_chases_misaligned_order(self):
        with patch.object(_gb, "chase_order") as mock_chase:
            _gb._execute_zone(SYMBOL, "SELL", "SELL", 2001.0, 1.0,
                              open_price_order=1800.0, pending_order_size=1.0,
                              remaining_capacity=2.0,
                              allow_chase=True, can_open=True)
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "SELL")

    def test_no_chase_when_price_aligned(self):
        with patch.object(_gb, "chase_order") as mock_chase, \
             patch.object(_gb, "new_order") as mock_new:
            _gb._execute_zone(SYMBOL, "SELL", "SELL", 2001.0, 1.0,
                              open_price_order=2001.0, pending_order_size=1.0,
                              remaining_capacity=2.0,
                              allow_chase=True, can_open=True)
        mock_chase.assert_not_called()
        mock_new.assert_not_called()

    def test_no_chase_when_pending_qty_zero(self):
        with patch.object(_gb, "chase_order") as mock_chase:
            _gb._execute_zone(SYMBOL, "BUY", "BUY", 2000.0, 1.0,
                              open_price_order=1900.0, pending_order_size=0.0,
                              remaining_capacity=2.0,
                              allow_chase=True, can_open=True)
        mock_chase.assert_not_called()

    def test_sell_new_order_at_ask_plus_boundary(self):
        mock_resp = SimpleNamespace(order_id="S1")
        with patch.object(_gb, "new_order", return_value=mock_resp) as mock_new:
            _gb._execute_zone(SYMBOL, "SELL", "BUY", 2000.0, 1.0,
                              open_price_order=0.0, pending_order_size=0.0,
                              remaining_capacity=2.0,
                              allow_chase=False, can_open=True)
        mock_new.assert_called_once_with(SYMBOL, 1.0, 2000.0 + BOUNDARY, "SELL")

    def test_buy_new_order_at_bid_minus_boundary(self):
        mock_resp = SimpleNamespace(order_id="B1")
        with patch.object(_gb, "new_order", return_value=mock_resp) as mock_new:
            _gb._execute_zone(SYMBOL, "BUY", "SELL", 2000.0, 1.0,
                              open_price_order=0.0, pending_order_size=0.0,
                              remaining_capacity=2.0,
                              allow_chase=False, can_open=True)
        mock_new.assert_called_once_with(SYMBOL, 1.0, 2000.0 - BOUNDARY, "BUY")

    def test_no_action_when_cannot_open_no_chase_positive_capacity(self):
        with patch.object(_gb, "new_order") as mock_new, \
             patch.object(_gb, "chase_order") as mock_chase, \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._execute_zone(SYMBOL, "BUY", "SELL", 2000.0, 1.0,
                              open_price_order=0.0, pending_order_size=0.0,
                              remaining_capacity=1.0,
                              allow_chase=False, can_open=False)
        mock_new.assert_not_called()
        mock_chase.assert_not_called()
        mock_cancel.assert_not_called()


# ---------------------------------------------------------------------------
# _process_tick
# ---------------------------------------------------------------------------

class TestProcessTick:

    def _run(self, snapshot, open_orders, bid, ask, position_amt,
             upper_limit=10.0, lower_limit=-10.0,
             max_pos=5.0, order_size=1.0,
             current_upper_diff=0.0, current_lower_diff=0.0):
        with patch.object(_gb, "get_open_orders", return_value=open_orders), \
             patch.object(_gb, "get_ticker", return_value=_ticker(bid, ask)), \
             patch.object(_gb, "get_position", return_value=_position(position_amt)):
            _gb._process_tick(
                SYMBOL, snapshot,
                CONTRACT_SIZE, MIN_TRADE,
                upper_limit, lower_limit, max_pos, order_size,
                current_upper_diff, current_lower_diff,
            )

    # --- sell zone ---

    def test_sell_zone_places_new_order(self):
        snapshot = _order_snapshot(status="FILLED", side="BUY")
        mock_resp = SimpleNamespace(order_id="S1")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_ticker", return_value=_ticker(2000.0, 2001.0)), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "new_order", return_value=mock_resp) as mock_new:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=6.0, current_lower_diff=0.0,
            )
        mock_new.assert_called_once_with(SYMBOL, 1.0, 2001.0 + BOUNDARY, "SELL")

    def test_buy_zone_places_new_order(self):
        snapshot = _order_snapshot(status="FILLED", side="SELL")
        mock_resp = SimpleNamespace(order_id="B1")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_ticker", return_value=_ticker(2000.0, 2001.0)), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "new_order", return_value=mock_resp) as mock_new:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=0.0, current_lower_diff=-6.0,
            )
        mock_new.assert_called_once_with(SYMBOL, 1.0, 2000.0 - BOUNDARY, "BUY")

    def test_within_range_no_action(self):
        snapshot = _order_snapshot(status="FILLED", side="BUY")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_ticker", return_value=_ticker(2000.0, 2001.0)), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "new_order") as mock_new, \
             patch.object(_gb, "chase_order") as mock_chase, \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=3.0, current_lower_diff=-3.0,
            )
        mock_new.assert_not_called()
        mock_chase.assert_not_called()
        mock_cancel.assert_not_called()

    def test_sell_zone_capacity_exceeded_cancels(self):
        """Position already at max — capacity < 0 triggers cancel."""
        snapshot = _order_snapshot(status="FILLED", side="BUY")
        sell_order = _open_order(side="SELL", price=2500.0, orig_qty=5.0)
        with patch.object(_gb, "get_open_orders", return_value=[sell_order]), \
             patch.object(_gb, "get_ticker", return_value=_ticker(2000.0, 2001.0)), \
             patch.object(_gb, "get_position", return_value=_position(-5.0)), \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=6.0, current_lower_diff=0.0,
            )
        mock_cancel.assert_called_once_with(SYMBOL)

    def test_sell_zone_chases_misaligned_order(self):
        """Open sell order at wrong price and status=NEW → chase."""
        snapshot = _order_snapshot(status="NEW", side="SELL")
        sell_order = _open_order(side="SELL", price=1800.0, orig_qty=1.0)
        with patch.object(_gb, "get_open_orders", return_value=[sell_order]), \
             patch.object(_gb, "get_ticker", return_value=_ticker(2000.0, 2001.0)), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=6.0, current_lower_diff=0.0,
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "SELL")

    def test_buy_zone_chases_misaligned_order(self):
        snapshot = _order_snapshot(status="NEW", side="BUY")
        buy_order = _open_order(side="BUY", price=1500.0, orig_qty=1.0)
        with patch.object(_gb, "get_open_orders", return_value=[buy_order]), \
             patch.object(_gb, "get_ticker", return_value=_ticker(2000.0, 2001.0)), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=0.0, current_lower_diff=-6.0,
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "BUY")

    # --- fractional position ---

    def test_fractional_position_places_new_sell_order(self):
        """position_amt=0.5 → unfilled fractional → place new order (no open orders)."""
        snapshot = _order_snapshot(status="FILLED", side="SELL")
        mock_resp = SimpleNamespace(order_id="F1")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_ticker", return_value=_ticker(2000.0, 2001.0)), \
             patch.object(_gb, "get_position", return_value=_position(0.5)), \
             patch.object(_gb, "new_order", return_value=mock_resp) as mock_new:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=0.0, current_lower_diff=0.0,
            )
        assert mock_new.call_count == 1
        _, args, _ = mock_new.mock_calls[0]
        assert args[3] == "SELL"                          # side
        assert args[2] == pytest.approx(2001.0 + BOUNDARY)   # price = ask + boundary

    def test_fractional_position_chases_existing_order(self):
        """Fractional + status=NEW → chase instead of new order."""
        snapshot = _order_snapshot(status="NEW", side="SELL")
        sell_order = _open_order(side="SELL", price=2500.0, orig_qty=0.5)
        with patch.object(_gb, "get_open_orders", return_value=[sell_order]), \
             patch.object(_gb, "get_ticker", return_value=_ticker(2000.0, 2001.0)), \
             patch.object(_gb, "get_position", return_value=_position(0.5)), \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=0.0, current_lower_diff=0.0,
            )
        assert mock_chase.call_count == 1
        assert mock_chase.call_args[0][2] == "SELL"

    def test_fractional_position_capacity_exceeded_cancels(self):
        """Fractional pos (-5.5) + sell pending=10 → capacity < 0 → cancel."""
        snapshot = _order_snapshot(status="FILLED", side="SELL")
        sell_order = _open_order(side="SELL", price=2500.0, orig_qty=10.0)
        with patch.object(_gb, "get_open_orders", return_value=[sell_order]), \
             patch.object(_gb, "get_ticker", return_value=_ticker(2000.0, 2001.0)), \
             patch.object(_gb, "get_position", return_value=_position(-5.5)), \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=0.0, current_lower_diff=0.0,
            )
        mock_cancel.assert_called_once_with(SYMBOL)

    # --- net pending ---

    def test_net_pending_buy_reduces_remaining_capacity(self):
        """Pending buy=4 + position=0, max=5 → capacity=1 → can still place sell."""
        snapshot = _order_snapshot(status="FILLED", side="BUY")
        buy_order = _open_order(side="BUY", price=2000.0, orig_qty=4.0)
        mock_resp = SimpleNamespace(order_id="NP1")
        with patch.object(_gb, "get_open_orders", return_value=[buy_order]), \
             patch.object(_gb, "get_ticker", return_value=_ticker(2000.0, 2001.0)), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "new_order", return_value=mock_resp) as mock_new:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=6.0, current_lower_diff=0.0,
            )
        mock_new.assert_called_once()

    def test_net_pending_full_capacity_cancels(self):
        """Pending buy=5 + position=0, max=5 → capacity=0 → cancel, not new order."""
        snapshot = _order_snapshot(status="FILLED", side="BUY")
        buy_order = _open_order(side="BUY", price=2000.0, orig_qty=5.0)
        with patch.object(_gb, "get_open_orders", return_value=[buy_order]), \
             patch.object(_gb, "get_ticker", return_value=_ticker(2000.0, 2001.0)), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "new_order") as mock_new, \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=6.0, current_lower_diff=0.0,
            )
        # capacity=0: can_open=False, allow_chase=False (status=FILLED) → no action
        mock_new.assert_not_called()

    # --- _record_new_order side effects ---

    def test_record_new_order_sets_last_acted_order_id(self):
        mock_resp = SimpleNamespace(order_id="REC1")
        _gb._record_new_order(mock_resp)
        assert _gb.last_acted_order_id == "REC1"
        assert _gb.optimistic_dirty_time > 0

    def test_record_new_order_none_response_does_not_crash(self):
        _gb._record_new_order(None)
        assert _gb.last_acted_order_id is None


# ---------------------------------------------------------------------------
# pubsub message builder smoke tests
# ---------------------------------------------------------------------------

class TestMessageHelpers:

    def test_price_message_roundtrips(self):
        msg = make_price_message("spread:binance:XAUUSDT", 7.5, -3.2)
        assert msg["type"] == "message"
        payload = json.loads(msg["data"])
        assert payload["current_upper_diff"] == 7.5
        assert payload["current_lower_diff"] == -3.2

    def test_grid_message_roundtrips(self):
        msg = make_grid_message("setting_grid_channel:XAUUSDT:XAUUSD",
                                5.0, -5.0, 10.0, 1.0)
        payload = json.loads(msg["data"])
        assert payload["upper_diff"] == 5.0
        assert payload["order_size"] == 1.0

    def test_price_message_feeds_into_parse(self):
        """Verify make_price_message produces a payload _process_tick can consume."""
        msg = make_price_message("ch", 8.0, -4.0)
        payload = json.loads(msg["data"])
        upper = round(float(payload.get("current_upper_diff", 0)), 2)
        lower = round(float(payload.get("current_lower_diff", 0)), 2)
        assert upper == 8.0
        assert lower == -4.0

    def test_grid_message_feeds_into_parse_settings(self):
        msg = make_grid_message("ch", 5.0, -5.0, 10.0, 2.0)
        payload = json.loads(msg["data"])
        settings = _gb._parse_grid_settings(payload)
        assert settings["upper"] == 5.0
        assert settings["order_size"] == 2.0
