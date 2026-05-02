"""
Automated tests for grid_bot trading logic.

External Binance calls (get_open_orders, get_position, cancel_all_open_orders,
chase_order) are patched on the loaded module object.
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
# helpers
# ---------------------------------------------------------------------------


def _open_order(side="BUY", price=2000.0, orig_qty=1.0):
    return SimpleNamespace(side=side, price=price, orig_qty=orig_qty)


def _position(amt=0.0):
    return {"positionAmt": str(amt)}


def make_price_message(channel: str, upper_limit: float, lower_limit: float) -> dict:
    """Return a dict shaped like a Redis pubsub price-diff message."""
    return {
        "type": "message",
        "channel": channel.encode(),
        "data": json.dumps({
            "current_upper_limit": upper_limit,
            "current_lower_limit": lower_limit,
        }).encode(),
    }


def make_grid_message(channel: str, upper_limit: float, lower_limit: float,
                      max_position_size: float, order_size: float) -> dict:
    """Return a dict shaped like a Redis pubsub grid-settings message."""
    return {
        "type": "message",
        "channel": channel.encode(),
        "data": json.dumps({
            "upper_limit": upper_limit,
            "lower_limit": lower_limit,
            "max_position_size": max_position_size,
            "order_size": order_size,
        }).encode(),
    }


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

SYMBOL = "XAUUSDT"


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
            "upper_limit": "10.5",
            "lower_limit": "-10.5",
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
# _determine_zone
# ---------------------------------------------------------------------------

class TestDetermineZone:

    def test_sell_zone(self):
        assert _gb._determine_zone(6.0, -2.0, 5.0, -5.0) == 'SELL'

    def test_buy_zone(self):
        assert _gb._determine_zone(2.0, -6.0, 5.0, -5.0) == 'BUY'

    def test_neutral_zone(self):
        assert _gb._determine_zone(2.0, -2.0, 5.0, -5.0) == 'NEUTRAL'

    def test_sell_zone_at_exact_limit(self):
        assert _gb._determine_zone(5.0, -2.0, 5.0, -5.0) == 'SELL'

    def test_buy_zone_at_exact_limit(self):
        assert _gb._determine_zone(2.0, -5.0, 5.0, -5.0) == 'BUY'

    def test_sell_takes_priority_when_both_breached(self):
        assert _gb._determine_zone(6.0, -6.0, 5.0, -5.0) == 'SELL'


# ---------------------------------------------------------------------------
# _compute_target
# ---------------------------------------------------------------------------

class TestComputeTarget:

    def test_sell_zone_returns_position_minus_order_size(self):
        assert _gb._compute_target('SELL', 0.0, 1.0, remaining_capacity=5.0) == -1.0

    def test_sell_zone_with_existing_position(self):
        assert _gb._compute_target('SELL', -1.0, 1.0, remaining_capacity=4.0) == -2.0

    def test_buy_zone_returns_position_plus_order_size(self):
        assert _gb._compute_target('BUY', 0.0, 1.0, remaining_capacity=5.0) == 1.0

    def test_buy_zone_with_existing_position(self):
        assert _gb._compute_target('BUY', 1.0, 1.0, remaining_capacity=4.0) == 2.0

    def test_neutral_returns_current_position(self):
        assert _gb._compute_target('NEUTRAL', 2.5, 1.0, remaining_capacity=5.0) == 2.5

    def test_neutral_flat_returns_zero(self):
        assert _gb._compute_target('NEUTRAL', 0.0, 1.0, remaining_capacity=5.0) == 0.0

    def test_capacity_exhausted_returns_current_position(self):
        assert _gb._compute_target('SELL', -4.0, 1.0, remaining_capacity=0.0) == -4.0
        assert _gb._compute_target('BUY',   4.0, 1.0, remaining_capacity=-1.0) == 4.0

    def test_capacity_exhausted_in_neutral_returns_current_position(self):
        assert _gb._compute_target('NEUTRAL', -3.0, 1.0, remaining_capacity=0.0) == -3.0


# ---------------------------------------------------------------------------
# _reconcile
# ---------------------------------------------------------------------------

class TestReconcile:

    def test_target_none_does_nothing(self):
        with patch.object(_gb, "cancel_all_open_orders") as mock_cancel, \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._reconcile(SYMBOL, None, 0.0, [])
        mock_cancel.assert_not_called()
        mock_chase.assert_not_called()

    def test_at_target_no_open_orders_does_nothing(self):
        with patch.object(_gb, "cancel_all_open_orders") as mock_cancel, \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._reconcile(SYMBOL, 0.0, 0.0, [])
        mock_cancel.assert_not_called()
        mock_chase.assert_not_called()

    def test_at_target_with_open_orders_cancels(self):
        with patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._reconcile(SYMBOL, 0.0, 0.0, [_open_order()])
        mock_cancel.assert_called_once_with(SYMBOL)

    def test_target_above_position_places_buy(self):
        mock_resp = SimpleNamespace(order_id="B1")
        with patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._reconcile(SYMBOL, 1.0, 0.0, [])
        mock_chase.assert_called_once_with(SYMBOL, 1.0, 'BUY')

    def test_target_below_position_places_sell(self):
        mock_resp = SimpleNamespace(order_id="S1")
        with patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._reconcile(SYMBOL, -1.0, 0.0, [])
        mock_chase.assert_called_once_with(SYMBOL, 1.0, 'SELL')

    def test_wrong_side_open_order_cancels(self):
        buy_order = _open_order(side='BUY')
        with patch.object(_gb, "cancel_all_open_orders") as mock_cancel, \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._reconcile(SYMBOL, -1.0, 0.0, [buy_order])  # want SELL, have BUY
        mock_cancel.assert_called_once_with(SYMBOL)
        mock_chase.assert_not_called()

    def test_right_side_open_order_chases(self):
        sell_order = _open_order(side='SELL', orig_qty=1.0)
        with patch.object(_gb, "chase_order") as mock_chase:
            _gb._reconcile(SYMBOL, -1.0, 0.0, [sell_order])
        mock_chase.assert_called_once_with(SYMBOL, 1.0, 'SELL')


# ---------------------------------------------------------------------------
# _process_tick
# ---------------------------------------------------------------------------

class TestProcessTick:

    def _run(self, open_orders, position_amt,
             upper_limit=10.0, lower_limit=-10.0,
             max_pos=5.0, order_size=1.0,
             current_upper_limit=0.0, current_lower_limit=0.0):
        with patch.object(_gb, "get_open_orders", return_value=open_orders), \
             patch.object(_gb, "get_position", return_value=_position(position_amt)):
            _gb._process_tick(
                SYMBOL,
                upper_limit, lower_limit, max_pos, order_size,
                current_upper_limit, current_lower_limit,
            )

    # --- sell / buy zone ---

    def test_sell_zone_places_new_order(self):
        mock_resp = SimpleNamespace(order_id="S1")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_limit=6.0, current_lower_limit=0.0,
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "SELL")

    def test_buy_zone_places_new_order(self):
        mock_resp = SimpleNamespace(order_id="B1")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_limit=0.0, current_lower_limit=-6.0,
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "BUY")

    def test_sell_zone_chases_existing_order(self):
        sell_order = _open_order(side="SELL", price=1800.0, orig_qty=1.0)
        with patch.object(_gb, "get_open_orders", return_value=[sell_order]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_limit=6.0, current_lower_limit=0.0,
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "SELL")

    def test_buy_zone_chases_existing_order(self):
        buy_order = _open_order(side="BUY", price=1000.0, orig_qty=1.0)
        with patch.object(_gb, "get_open_orders", return_value=[buy_order]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_limit=0.0, current_lower_limit=-6.0,
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "BUY")

    def test_sell_zone_wrong_side_open_order_cancels(self):
        buy_order = _open_order(side="BUY", price=2000.0, orig_qty=1.0)
        with patch.object(_gb, "get_open_orders", return_value=[buy_order]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel, \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_limit=6.0, current_lower_limit=0.0,
            )
        mock_cancel.assert_called_once_with(SYMBOL)
        mock_chase.assert_not_called()

    def test_sell_zone_capacity_exceeded_cancels(self):
        """Position at max + pending sell → capacity ≤ 0 → target=pos → cancel."""
        sell_order = _open_order(side="SELL", price=2500.0, orig_qty=5.0)
        with patch.object(_gb, "get_open_orders", return_value=[sell_order]), \
             patch.object(_gb, "get_position", return_value=_position(-5.0)), \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_limit=6.0, current_lower_limit=0.0,
            )
        mock_cancel.assert_called_once_with(SYMBOL)

    def test_capacity_zero_with_pending_order_cancels(self):
        """Pending buy fills capacity (max=5) → target=pos → cancel."""
        buy_order = _open_order(side="BUY", price=2000.0, orig_qty=5.0)
        with patch.object(_gb, "get_open_orders", return_value=[buy_order]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel, \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_limit=6.0, current_lower_limit=0.0,
            )
        mock_cancel.assert_called_once_with(SYMBOL)
        mock_chase.assert_not_called()

    # --- neutral zone ---

    def test_neutral_flat_no_open_orders_does_nothing(self):
        """Neutral zone, flat position, no open orders → nothing."""
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order") as mock_chase, \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_limit=3.0, current_lower_limit=-3.0,
            )
        mock_chase.assert_not_called()
        mock_cancel.assert_not_called()

    def test_neutral_with_open_order_cancels(self):
        """Neutral zone, open order sitting → target=pos → cancel it."""
        sell_order = _open_order(side='SELL', price=2501.0, orig_qty=1.0)
        with patch.object(_gb, "get_open_orders", return_value=[sell_order]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_limit=2.0, current_lower_limit=-2.0,
            )
        mock_cancel.assert_called_once_with(SYMBOL)

    def test_neutral_with_position_no_open_orders_does_nothing(self):
        """Neutral zone, has position but no open orders → target=pos → nothing to cancel."""
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(-2.0)), \
             patch.object(_gb, "chase_order") as mock_chase, \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_limit=2.0, current_lower_limit=-2.0,
            )
        mock_chase.assert_not_called()
        mock_cancel.assert_not_called()

    # --- sell zone accumulation ---

    def test_sell_accumulates_until_max_position(self):
        """SELL zone: each filled order shifts position; next tick places the next one."""
        mock_resp = SimpleNamespace(order_id="S1")
        # Step 1: pos=0 → target=-1 → place SELL 1
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._process_tick(SYMBOL, 5.0, -5.0, 3.0, 1.0, 6.0, 0.0)
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "SELL")

        # Step 2: pos=-1 → target=-2 → place SELL 1
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(-1.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._process_tick(SYMBOL, 5.0, -5.0, 3.0, 1.0, 6.0, 0.0)
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "SELL")

        # Step 3: pos=-2 → target=-3 → place SELL 1
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(-2.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._process_tick(SYMBOL, 5.0, -5.0, 3.0, 1.0, 6.0, 0.0)
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "SELL")

        # Step 4: pos=-3 → capacity=0 → target=pos → no open order → nothing
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(-3.0)), \
             patch.object(_gb, "chase_order") as mock_chase, \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._process_tick(SYMBOL, 5.0, -5.0, 3.0, 1.0, 6.0, 0.0)
        mock_chase.assert_not_called()
        mock_cancel.assert_not_called()

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
        assert payload["current_upper_limit"] == 7.5
        assert payload["current_lower_limit"] == -3.2

    def test_grid_message_roundtrips(self):
        msg = make_grid_message("setting_grid_channel:XAUUSDT:XAUUSD",
                                5.0, -5.0, 10.0, 1.0)
        payload = json.loads(msg["data"])
        assert payload["upper_limit"] == 5.0
        assert payload["order_size"] == 1.0

    def test_price_message_feeds_into_parse(self):
        """Verify make_price_message produces a payload _process_tick can consume."""
        msg = make_price_message("ch", 8.0, -4.0)
        payload = json.loads(msg["data"])
        upper = round(float(payload.get("current_upper_limit", 0)), 2)
        lower = round(float(payload.get("current_lower_limit", 0)), 2)
        assert upper == 8.0
        assert lower == -4.0

    def test_grid_message_feeds_into_parse_settings(self):
        msg = make_grid_message("ch", 5.0, -5.0, 10.0, 2.0)
        payload = json.loads(msg["data"])
        settings = _gb._parse_grid_settings(payload)
        assert settings["upper"] == 5.0
        assert settings["order_size"] == 2.0
