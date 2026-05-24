"""
Automated tests for grid_bot trading logic.

External Binance calls (get_open_orders, get_position, cancel_all_open_orders,
chase_order) are patched on the loaded module object.
"""
import json
import logging
import sys
import time
import types
import threading
import importlib.util
import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

logger = logging.getLogger(__name__)

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
    "fill_pct": 0, "side": None, "price": None, "orig_qty": 0,
}
_state_mod.force_position_fetch = False
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


def _open_order(side="BUY", price=2000.0, orig_qty=1.0, order_id=None):
    return SimpleNamespace(side=side, price=price, orig_qty=orig_qty, order_id=order_id)


def _position(amt=0.0):
    return {"positionAmt": str(amt)}


def make_price_message(channel: str, upper_limit: float, lower_limit: float,
                       ts: float = None) -> dict:
    """Return a dict shaped like a Redis pubsub price-diff message."""
    payload = {"ask_diff": upper_limit, "bid_diff": lower_limit}
    if ts is not None:
        payload["ts"] = ts
    return {
        "type": "message",
        "channel": channel.encode(),
        "data": json.dumps(payload).encode(),
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
    _gb.latest_ask_diff = None
    _gb.latest_bid_diff = None
    _gb.latest_grid_settings = None
    _gb.latest_atr = 0.0
    _gb._prev_ask_diff_for_atr = None
    _gb._prev_bid_diff_for_atr = None
    _state_mod.force_position_fetch = False
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
# _compute_target — truncation towards zero
# ---------------------------------------------------------------------------

class TestComputeTargetTruncation:
    """Target must be truncated towards zero (math.trunc), not floored."""

    # --- BUY zone (positive result) ---

    def test_buy_fractional_position_truncates_down(self):
        # 0.531 + 1.0 = 1.531 → trunc → 1  (not 2)
        assert _gb._compute_target('BUY', 0.531, 1.0, remaining_capacity=5.0) == 1

    def test_buy_large_fractional_position_truncates(self):
        # real-world case from logs: 287.531 + 1.0 = 288.531 → trunc → 288
        assert _gb._compute_target('BUY', 287.531, 1.0, remaining_capacity=5.0) == 288

    def test_buy_result_near_zero_truncates_to_zero(self):
        # -0.8 + 1.0 = 0.2 → trunc → 0
        assert _gb._compute_target('BUY', -0.8, 1.0, remaining_capacity=5.0) == 0

    # --- SELL zone (negative result) ---

    def test_sell_fractional_position_truncates_towards_zero(self):
        # -0.531 - 1.0 = -1.531 → trunc → -1  (not -2, which floor would give)
        assert _gb._compute_target('SELL', -0.531, 1.0, remaining_capacity=5.0) == -1

    def test_sell_large_fractional_position_truncates_towards_zero(self):
        # -287.531 - 1.0 = -288.531 → trunc → -288  (not -289)
        assert _gb._compute_target('SELL', -287.531, 1.0, remaining_capacity=5.0) == -288

    def test_sell_result_near_zero_truncates_to_zero(self):
        # 0.8 - 1.0 = -0.2 → trunc → 0  (not -1 which floor would give)
        assert _gb._compute_target('SELL', 0.8, 1.0, remaining_capacity=5.0) == 0

    # --- trunc vs floor distinction ---

    def test_trunc_differs_from_floor_for_negative(self):
        # This is the key property: trunc(-1.531)==-1, floor(-1.531)==-2
        result = _gb._compute_target('SELL', -0.531, 1.0, remaining_capacity=5.0)
        assert result == -1, f"Expected -1 (trunc), got {result} (floor would give -2)"

    # --- whole numbers are unaffected ---

    def test_whole_number_buy_unchanged(self):
        assert _gb._compute_target('BUY', 0.0, 1.0, remaining_capacity=5.0) == 1

    def test_whole_number_sell_unchanged(self):
        assert _gb._compute_target('SELL', 0.0, 1.0, remaining_capacity=5.0) == -1


# ---------------------------------------------------------------------------
# _compute_target — contract_size (MOCK_ENTRY_POSITION_AMT) truncation
# ---------------------------------------------------------------------------

class TestComputeTargetContractSize:
    """
    When contract_size is passed, the target is truncated to the nearest
    1/contract_size lot (trunc(val * contract_size) / contract_size) instead
    of the nearest integer.
    """

    # --- BUY zone ---

    def test_buy_exact_lot_unchanged(self):
        # 0 + 0.01 = 0.01 → trunc(0.01 × 100)/100 = trunc(1.0)/100 = 0.01
        assert _gb._compute_target('BUY', 0.0, 0.01, 5.0, contract_size=100) == pytest.approx(0.01)

    def test_buy_fractional_lot_truncated_down(self):
        # 0 + 0.012 = 0.012 → trunc(1.2)/100 = 0.01   (not 0.02)
        assert _gb._compute_target('BUY', 0.0, 0.012, 5.0, contract_size=100) == pytest.approx(0.01)

    def test_buy_accumulates_with_existing_position(self):
        # 0.01 + 0.01 = 0.02 → trunc(2.0)/100 = 0.02
        assert _gb._compute_target('BUY', 0.01, 0.01, 5.0, contract_size=100) == pytest.approx(0.02)

    def test_buy_fractional_lot_with_existing_position(self):
        # 0.01 + 0.012 = 0.022 → trunc(2.2)/100 = 0.02
        assert _gb._compute_target('BUY', 0.01, 0.012, 5.0, contract_size=100) == pytest.approx(0.02)

    # --- SELL zone ---

    def test_sell_exact_lot_unchanged(self):
        # 0 - 0.01 = -0.01 → trunc(-1.0)/100 = -0.01
        assert _gb._compute_target('SELL', 0.0, 0.01, 5.0, contract_size=100) == pytest.approx(-0.01)

    def test_sell_fractional_lot_truncates_towards_zero(self):
        # 0 - 0.012 = -0.012 → trunc(-1.2)/100 = -0.01   (not -0.02)
        assert _gb._compute_target('SELL', 0.0, 0.012, 5.0, contract_size=100) == pytest.approx(-0.01)

    def test_sell_accumulates_with_existing_negative_position(self):
        # -0.01 - 0.01 = -0.02 → trunc(-2.0)/100 = -0.02
        assert _gb._compute_target('SELL', -0.01, 0.01, 5.0, contract_size=100) == pytest.approx(-0.02)

    def test_sell_fractional_lot_with_existing_negative_position(self):
        # -0.01 - 0.012 = -0.022 → trunc(-2.2)/100 = -0.02
        assert _gb._compute_target('SELL', -0.01, 0.012, 5.0, contract_size=100) == pytest.approx(-0.02)

    # --- NEUTRAL / capacity exhausted — short-circuit, no truncation ---

    def test_neutral_returns_position_unchanged(self):
        assert _gb._compute_target('NEUTRAL', 0.05, 0.01, 5.0, contract_size=100) == 0.05

    def test_capacity_exhausted_returns_position_unchanged(self):
        assert _gb._compute_target('BUY', 0.05, 0.01, 0.0, contract_size=100) == 0.05

    # --- without contract_size — existing integer truncation unaffected ---

    def test_without_contract_size_buy_integer_trunc(self):
        assert _gb._compute_target('BUY', 0.0, 1.0, 5.0) == 1

    def test_without_contract_size_sell_integer_trunc(self):
        assert _gb._compute_target('SELL', 0.0, 1.0, 5.0) == -1


# ---------------------------------------------------------------------------
# _process_tick — MOCK_ENTRY_POSITION_AMT integration
# ---------------------------------------------------------------------------

class TestProcessTickMockEntryPosition:
    """MOCK_ENTRY_POSITION_AMT=true routes contract_size through to _compute_target."""

    def test_valid_lot_order_size_places_order(self):
        """order_size=0.01, contract_size=100 → 0.01×100=1 (integer) → valid lot."""
        mock_resp = SimpleNamespace(order_id="B1")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase, \
             patch.dict("os.environ", {"MOCK_ENTRY_POSITION_AMT": "true", "PAIR_INDEX": "0"}):
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=0.01,
                ask_diff=0.0, bid_diff=-6.0,  # BUY zone
            )
        mock_chase.assert_called_once_with(SYMBOL, pytest.approx(0.01), "BUY", order_id=None)

    def test_fractional_lot_order_size_is_truncated(self):
        """order_size=0.012 → trunc(0.012×100)/100=0.01 → chase_order receives 0.01."""
        mock_resp = SimpleNamespace(order_id="B1")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase, \
             patch.dict("os.environ", {"MOCK_ENTRY_POSITION_AMT": "true", "PAIR_INDEX": "0"}):
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=0.012,
                ask_diff=0.0, bid_diff=-6.0,  # BUY zone
            )
        mock_chase.assert_called_once_with(SYMBOL, pytest.approx(0.01), "BUY", order_id=None)

    def test_sell_zone_fractional_lot_truncated(self):
        """SELL zone: order_size=0.012 → truncated to 0.01."""
        mock_resp = SimpleNamespace(order_id="S1")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase, \
             patch.dict("os.environ", {"MOCK_ENTRY_POSITION_AMT": "true", "PAIR_INDEX": "0"}):
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=0.012,
                ask_diff=6.0, bid_diff=0.0,  # SELL zone
            )
        mock_chase.assert_called_once_with(SYMBOL, pytest.approx(0.01), "SELL", order_id=None)

    def test_mock_entry_false_uses_integer_truncation(self):
        """MOCK_ENTRY_POSITION_AMT=false → standard integer truncation, no change."""
        mock_resp = SimpleNamespace(order_id="B1")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase, \
             patch.dict("os.environ", {"MOCK_ENTRY_POSITION_AMT": "false", "PAIR_INDEX": "0"}):
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                ask_diff=0.0, bid_diff=-6.0,  # BUY zone
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "BUY", order_id=None)


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
        mock_chase.assert_called_once_with(SYMBOL, 1.0, 'BUY', order_id=None)

    def test_target_below_position_places_sell(self):
        mock_resp = SimpleNamespace(order_id="S1")
        with patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._reconcile(SYMBOL, -1.0, 0.0, [])
        mock_chase.assert_called_once_with(SYMBOL, 1.0, 'SELL', order_id=None)

    def test_wrong_side_open_order_cancels(self):
        buy_order = _open_order(side='BUY')
        with patch.object(_gb, "cancel_all_open_orders") as mock_cancel, \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._reconcile(SYMBOL, -1.0, 0.0, [buy_order])  # want SELL, have BUY
        mock_cancel.assert_called_once_with(SYMBOL)
        mock_chase.assert_not_called()

    def test_right_side_open_order_chases(self):
        sell_order = _open_order(side='SELL', orig_qty=1.0, order_id=42)
        with patch.object(_gb, "chase_order") as mock_chase:
            _gb._reconcile(SYMBOL, -1.0, 0.0, [sell_order])
        mock_chase.assert_called_once_with(SYMBOL, 1.0, 'SELL', order_id=42)


# ---------------------------------------------------------------------------
# _process_tick
# ---------------------------------------------------------------------------

class TestProcessTick:

    def _run(self, open_orders, position_amt,
             upper_limit=10.0, lower_limit=-10.0,
             max_pos=5.0, order_size=1.0,
             ask_diff=0.0, bid_diff=0.0):
        with patch.object(_gb, "get_open_orders", return_value=open_orders), \
             patch.object(_gb, "get_position", return_value=_position(position_amt)):
            _gb._process_tick(
                SYMBOL,
                upper_limit, lower_limit, max_pos, order_size,
                ask_diff, bid_diff,
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
                ask_diff=6.0, bid_diff=0.0,
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "SELL", order_id=None)

    def test_buy_zone_places_new_order(self):
        mock_resp = SimpleNamespace(order_id="B1")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                ask_diff=0.0, bid_diff=-6.0,
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "BUY", order_id=None)

    def test_sell_zone_chases_existing_order(self):
        sell_order = _open_order(side="SELL", price=1800.0, orig_qty=1.0, order_id=77)
        with patch.object(_gb, "get_open_orders", return_value=[sell_order]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                ask_diff=6.0, bid_diff=0.0,
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "SELL", order_id=77)

    def test_buy_zone_chases_existing_order(self):
        buy_order = _open_order(side="BUY", price=1000.0, orig_qty=1.0, order_id=88)
        with patch.object(_gb, "get_open_orders", return_value=[buy_order]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._process_tick(
                SYMBOL,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                ask_diff=0.0, bid_diff=-6.0,
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "BUY", order_id=88)

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
                ask_diff=6.0, bid_diff=0.0,
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
                ask_diff=6.0, bid_diff=0.0,
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
                ask_diff=6.0, bid_diff=0.0,
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
                ask_diff=3.0, bid_diff=-3.0,
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
                ask_diff=2.0, bid_diff=-2.0,
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
                ask_diff=2.0, bid_diff=-2.0,
            )
        mock_chase.assert_not_called()
        mock_cancel.assert_not_called()

    # --- sell zone accumulation ---

    def test_sell_accumulates_until_max_position(self):
        """SELL zone: each filled order shifts position; next tick places the next one."""
        mock_resp = SimpleNamespace(order_id="S1")
        # Step 1: pos=0 → target=-1 → place SELL 1 (no open order → order_id=None)
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._process_tick(SYMBOL, 5.0, -5.0, 3.0, 1.0, 6.0, 0.0)
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "SELL", order_id=None)

        # Step 2: pos=-1 → target=-2 → place SELL 1
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(-1.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._process_tick(SYMBOL, 5.0, -5.0, 3.0, 1.0, 6.0, 0.0)
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "SELL", order_id=None)

        # Step 3: pos=-2 → target=-3 → place SELL 1
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(-2.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._process_tick(SYMBOL, 5.0, -5.0, 3.0, 1.0, 6.0, 0.0)
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "SELL", order_id=None)

        # Step 4: pos=-3 → capacity=0 → target=pos → no open order → nothing
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(-3.0)), \
             patch.object(_gb, "chase_order") as mock_chase, \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._process_tick(SYMBOL, 5.0, -5.0, 3.0, 1.0, 6.0, 0.0)
        mock_chase.assert_not_called()
        mock_cancel.assert_not_called()



# ---------------------------------------------------------------------------
# pubsub message builder smoke tests
# ---------------------------------------------------------------------------

class TestMessageHelpers:

    def test_price_message_roundtrips(self):
        msg = make_price_message("spread:binance:XAUUSDT", 7.5, -3.2)
        assert msg["type"] == "message"
        payload = json.loads(msg["data"])
        assert payload["ask_diff"] == 7.5
        assert payload["bid_diff"] == -3.2

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
        upper = round(float(payload.get("ask_diff", 0)), 2)
        lower = round(float(payload.get("bid_diff", 0)), 2)
        assert upper == 8.0
        assert lower == -4.0

    def test_grid_message_feeds_into_parse_settings(self):
        msg = make_grid_message("ch", 5.0, -5.0, 10.0, 2.0)
        payload = json.loads(msg["data"])
        settings = _gb._parse_grid_settings(payload)
        assert settings["upper"] == 5.0
        assert settings["order_size"] == 2.0

    def test_price_message_includes_ts_when_provided(self):
        now = time.time()
        msg = make_price_message("ch", 5.0, -3.0, ts=now)
        payload = json.loads(msg["data"])
        assert payload["ts"] == now

    def test_price_message_omits_ts_by_default(self):
        msg = make_price_message("ch", 5.0, -3.0)
        payload = json.loads(msg["data"])
        assert "ts" not in payload


# ---------------------------------------------------------------------------
# handle_grid_flow — stale price diff protection
# ---------------------------------------------------------------------------

class _StopLoop(BaseException):
    """Sentinel raised to break the infinite while-loop in handle_grid_flow.

    Must subclass BaseException, not Exception, because handle_grid_flow has a
    bare `except Exception` that would otherwise swallow this and loop forever.
    """


def _run_handle_grid_flow_with_messages(messages, env_overrides=None):
    """
    Drive handle_grid_flow with a fixed list of pubsub messages, then stop.

    Returns (latest_ask_diff, latest_bid_diff) after all messages are consumed.
    """
    price_key = "spread:binance:XAUUSDT"
    grid_key = "setting_grid_channel:XAUUSDT:XAUUSD"

    call_count = [0]

    def listen_side_effect():
        call_count[0] += 1
        if call_count[0] > 1:
            raise _StopLoop("done")
        return iter(messages)

    pubsub = MagicMock()
    pubsub.listen.side_effect = listen_side_effect

    redis_mock = MagicMock()
    redis_mock.get.return_value = None

    env = {"PAIR_INDEX": "0", **(env_overrides or {})}

    with patch.dict("os.environ", env), \
         patch.object(_gb, "get_redis_connection", return_value=redis_mock), \
         patch.object(_gb, "get_active_status", return_value=None), \
         patch.object(_gb, "_process_tick"):
        try:
            _gb.handle_grid_flow(pubsub, price_key, grid_key)
        except _StopLoop:
            pass

    return _gb.latest_ask_diff, _gb.latest_bid_diff


PRICE_CH = "spread:binance:XAUUSDT"


class TestHandleGridFlowStalePriceDiff:

    def test_fresh_message_updates_globals(self):
        """A price_diff message with a recent ts should update latest_ask/bid_diff."""
        msg = make_price_message(PRICE_CH, 7.5, -3.2, ts=time.time())
        ask, bid = _run_handle_grid_flow_with_messages([msg])
        assert ask == 7.5
        assert bid == -3.2

    def test_stale_message_is_dropped(self):
        """A price_diff message older than PRICE_DIFF_MAX_AGE_MS must be ignored."""
        stale_ts = time.time() - 1.0  # 1 second ago — way past any threshold
        msg = make_price_message(PRICE_CH, 99.0, -99.0, ts=stale_ts)
        ask, bid = _run_handle_grid_flow_with_messages([msg])
        assert ask is None
        assert bid is None

    def test_message_without_ts_is_accepted(self):
        """Backward-compat: messages without a ts field must still update globals."""
        msg = make_price_message(PRICE_CH, 5.0, -5.0)  # no ts
        ask, bid = _run_handle_grid_flow_with_messages([msg])
        assert ask == 5.0
        assert bid == -5.0

    def test_stale_then_fresh_keeps_fresh_value(self):
        """After a stale drop, a subsequent fresh message should still be applied."""
        stale_ts = time.time() - 1.0
        stale = make_price_message(PRICE_CH, 99.0, -99.0, ts=stale_ts)
        fresh = make_price_message(PRICE_CH, 4.0, -2.0, ts=time.time())

        ask, bid = _run_handle_grid_flow_with_messages([stale, fresh])
        assert ask == 4.0
        assert bid == -2.0

    def test_custom_max_age_env_respected(self):
        """PRICE_DIFF_MAX_AGE_MS env var should control the staleness threshold."""
        # 50 ms threshold; message is ~100 ms old → should be dropped
        ts_100ms_ago = time.time() - 0.1
        msg = make_price_message(PRICE_CH, 8.0, -8.0, ts=ts_100ms_ago)

        # Reload the module-level constant via env override — we patch the
        # attribute directly since the module constant is already bound.
        original = _gb.PRICE_DIFF_MAX_AGE_MS
        _gb.PRICE_DIFF_MAX_AGE_MS = 50  # 50 ms < 100 ms → drop
        try:
            ask, bid = _run_handle_grid_flow_with_messages([msg])
        finally:
            _gb.PRICE_DIFF_MAX_AGE_MS = original

        assert ask is None
        assert bid is None


# ---------------------------------------------------------------------------
# ATR computation
# ---------------------------------------------------------------------------

_ATR_ALPHA = 2.0 / (14 + 1)  # mirrors module default (ATR_PERIOD=14)


class TestATRComputation:

    def test_first_message_atr_stays_zero(self):
        """No previous value to diff against → ATR remains 0."""
        msg = make_price_message(PRICE_CH, 3.0, 3.2, ts=time.time())
        _run_handle_grid_flow_with_messages([msg])
        assert _gb.latest_atr == 0.0

    def test_second_message_computes_atr_from_ask_delta(self):
        """When ask delta dominates, TR = |Δask|."""
        msg1 = make_price_message(PRICE_CH, 1.5, 1.6, ts=time.time())
        msg2 = make_price_message(PRICE_CH, 3.0, 1.7, ts=time.time())  # ask Δ=1.5, bid Δ=0.1
        _run_handle_grid_flow_with_messages([msg1, msg2])
        expected = _ATR_ALPHA * 1.5  # prev ATR was 0
        assert abs(_gb.latest_atr - expected) < 1e-9

    def test_second_message_uses_max_of_ask_and_bid_delta(self):
        """When bid delta dominates, TR = |Δbid|."""
        msg1 = make_price_message(PRICE_CH, 3.0, 1.0, ts=time.time())
        msg2 = make_price_message(PRICE_CH, 3.5, 3.0, ts=time.time())  # ask Δ=0.5, bid Δ=2.0
        _run_handle_grid_flow_with_messages([msg1, msg2])
        expected = _ATR_ALPHA * 2.0
        assert abs(_gb.latest_atr - expected) < 1e-9

    def test_atr_decays_after_spike(self):
        """After a large spike, calm ticks reduce ATR each step."""
        msg1 = make_price_message(PRICE_CH, 1.56, 1.69, ts=time.time())
        msg2 = make_price_message(PRICE_CH, 4.29, 4.41, ts=time.time())  # spike: ask Δ=2.73
        msg3 = make_price_message(PRICE_CH, 4.30, 4.42, ts=time.time())  # calm: Δ=0.01
        msg4 = make_price_message(PRICE_CH, 4.31, 4.43, ts=time.time())  # calm: Δ=0.01
        _run_handle_grid_flow_with_messages([msg1, msg2, msg3, msg4])

        atr_spike  = _ATR_ALPHA * 2.73
        atr_calm1  = _ATR_ALPHA * 0.01 + (1 - _ATR_ALPHA) * atr_spike
        atr_calm2  = _ATR_ALPHA * 0.01 + (1 - _ATR_ALPHA) * atr_calm1
        assert abs(_gb.latest_atr - atr_calm2) < 1e-6
        assert _gb.latest_atr < atr_spike

    def test_stale_message_does_not_update_atr(self):
        """Dropped stale messages must not advance ATR state."""
        stale_ts = time.time() - 1.0
        msg = make_price_message(PRICE_CH, 5.0, 5.2, ts=stale_ts)
        _run_handle_grid_flow_with_messages([msg])
        assert _gb.latest_atr == 0.0
        assert _gb._prev_ask_diff_for_atr is None

    def test_real_glitch_spike_exceeds_threshold(self):
        """The 1.56→4.29 glitch seen in prod logs must push ATR above the default threshold."""
        msg1 = make_price_message(PRICE_CH, 1.56, 1.69, ts=time.time())
        msg2 = make_price_message(PRICE_CH, 4.29, 4.41, ts=time.time())
        _run_handle_grid_flow_with_messages([msg1, msg2])
        assert _gb.latest_atr > _gb.ATR_HIGH_THRESHOLD


# ---------------------------------------------------------------------------
# ATR volatility gate (_tick_worker integration)
# ---------------------------------------------------------------------------

def _run_handle_grid_flow_active(messages):
    """
    Drive handle_grid_flow with active=True and initial grid settings loaded.
    Returns True if _process_tick was called at least once by the tick worker.
    """
    price_key = "spread:binance:XAUUSDT"
    grid_key = "setting_grid_channel:XAUUSDT:XAUUSD"

    call_count = [0]
    process_tick_called = [False]

    def listen_side_effect():
        call_count[0] += 1
        if call_count[0] > 1:
            raise _StopLoop("done")
        return iter(messages)

    pubsub = MagicMock()
    pubsub.listen.side_effect = listen_side_effect

    redis_mock = MagicMock()
    grid_data = json.dumps({
        "upper_limit": 5.0, "lower_limit": -5.0,
        "max_position_size": 5.0, "order_size": 1.0,
    })
    redis_mock.get.return_value = grid_data.encode()

    def mock_process_tick(*args, **kwargs):
        process_tick_called[0] = True
        logger.info(f"[TickWorker] _process_tick reached: ask_diff={args[5] if len(args) > 5 else '?'} bid_diff={args[6] if len(args) > 6 else '?'}")

    with patch.dict("os.environ", {"PAIR_INDEX": "0"}), \
         patch.object(_gb, "get_redis_connection", return_value=redis_mock), \
         patch.object(_gb, "get_active_status", return_value=b"1"), \
         patch.object(_gb, "_process_tick", side_effect=mock_process_tick):
        try:
            _gb.handle_grid_flow(pubsub, price_key, grid_key)
        except _StopLoop:
            time.sleep(0.25)  # let tick_worker run while patch is still active

    return process_tick_called[0]


class TestATRVolatilityGate:

    def test_process_tick_allowed_when_atr_normal(self):
        """Small consecutive deltas keep ATR low → _process_tick is called."""
        msg1 = make_price_message(PRICE_CH, 3.0, 3.1, ts=time.time())
        msg2 = make_price_message(PRICE_CH, 3.1, 3.2, ts=time.time())  # Δ=0.1 → ATR ≈ 0.013
        assert _run_handle_grid_flow_active([msg1, msg2]) is True

    def test_process_tick_blocked_when_atr_high(self):
        """1.56→4.29 spike raises ATR above threshold → _process_tick is NOT called."""
        msg1 = make_price_message(PRICE_CH, 1.56, 1.69, ts=time.time())
        msg2 = make_price_message(PRICE_CH, 4.29, 4.41, ts=time.time())  # ATR ≈ 0.364
        assert _run_handle_grid_flow_active([msg1, msg2]) is False

    def test_atr_rise_and_decay_unblocks_after_two_calm_ticks(self):
        """
        ATR lifecycle after a spike (threshold=0.3):
          spike        → ATR=0.364  blocked
          spike+calm×1 → ATR=0.317  still blocked
          spike+calm×2 → ATR=0.276  unblocked
        Each call replays from scratch so ATR is built fresh from the message sequence.
        Messages omit ts to avoid the stale-price-diff filter across the three sequential calls.
        """
        def msgs(*price_pairs):
            return [make_price_message(PRICE_CH, ask, bid) for ask, bid in price_pairs]

        # (ask, bid) sequence: baseline → spike → calm ticks
        baseline = (1.56, 1.69)
        spike    = (4.29, 4.41)  # Δ=2.73 → ATR=0.364
        calm1    = (4.30, 4.42)  # Δ=0.01 → ATR≈0.317
        calm2    = (4.31, 4.43)  # Δ=0.01 → ATR≈0.276

        assert _run_handle_grid_flow_active(msgs(baseline, spike)) is False, \
            "spike should block immediately"
        assert _run_handle_grid_flow_active(msgs(baseline, spike, calm1)) is False, \
            "one calm tick is not enough to recover"
        assert _run_handle_grid_flow_active(msgs(baseline, spike, calm1, calm2)) is True, \
            "two calm ticks should bring ATR below threshold and unblock"


# ---------------------------------------------------------------------------
# watch_user_data_stream — on_message handler
# ---------------------------------------------------------------------------

class _StopUserStream(BaseException):
    """Abort watch_user_data_stream's while-True loop from run_forever.

    Must subclass BaseException so it isn't caught by the bare
    ``except Exception`` inside watch_user_data_stream.
    """


def _capture_on_message(symbol="XAUUSDT"):
    """
    Drive watch_user_data_stream just far enough to capture the on_message
    closure, then abort.

    The returned callable shares the same ``order_status`` dict for its whole
    lifetime, accurately modelling a live WebSocket session where multiple
    order events arrive on the same connection.
    """
    captured: dict = {}

    class _FakeWSApp:
        def __init__(self, url, on_open=None, on_message=None,
                     on_error=None, on_close=None):
            captured["on_message"] = on_message

        def run_forever(self, **kwargs):
            raise _StopUserStream()

    fake_stream = MagicMock()
    fake_stream.data.return_value.listen_key = "test_key"

    with patch.object(_gb.binance_client.rest_api, "start_user_data_stream",
                      return_value=fake_stream), \
         patch.object(_gb.websocket, "WebSocketApp", _FakeWSApp):
        try:
            _gb.watch_user_data_stream(symbol)
        except _StopUserStream:
            pass

    return captured["on_message"]


def _order_event(order_id, status, *, side="BUY", symbol="XAUUSDT",
                 orig_qty=1.0, executed_qty=0.0, price="2000.0"):
    """Return a serialised ORDER_TRADE_UPDATE WebSocket message."""
    return json.dumps({
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "s": symbol,
            "i": order_id,
            "X": status,
            "S": side,
            "q": str(orig_qty),
            "z": str(executed_qty),
            "p": price,
            "L": "0.0",
            "ap": "0.0",
        },
    })


class TestOnMessage:
    """Unit tests for the on_message closure inside watch_user_data_stream."""

    @pytest.fixture(autouse=True)
    def reset_order_state(self):
        """Isolate placing_order_state and force_position_fetch between tests."""
        def _reset():
            _state_mod.placing_order_state.update({
                "order_id": None, "status": None, "is_clean": True,
                "fill_pct": 0, "side": None, "price": None, "orig_qty": 0,
            })
            _state_mod.force_position_fetch = False

        _reset()
        yield
        _reset()

    # --- basic state updates ---

    def test_state_updated_on_new_order(self):
        on_msg = _capture_on_message()
        on_msg(None, _order_event(111, "NEW", side="SELL"))
        with _state_mod.state_lock:
            s = dict(_state_mod.placing_order_state)
        assert s["order_id"] == 111
        assert s["status"] == "NEW"
        assert s["side"] == "SELL"
        assert s["is_clean"] is False

    def test_state_updated_on_filled_order(self):
        on_msg = _capture_on_message()
        on_msg(None, _order_event(111, "FILLED", orig_qty=2.0, executed_qty=2.0))
        with _state_mod.state_lock:
            s = dict(_state_mod.placing_order_state)
        assert s["order_id"] == 111
        assert s["status"] == "FILLED"
        assert s["fill_pct"] == 100.0
        assert s["is_clean"] is True

    # --- core cross-order reset scenario ---

    def test_placing_order_state_reflects_order2_after_order1_filled(self):
        """
        placing_order_state must be overwritten with Order 2's data when its
        event arrives, regardless of Order 1's previous terminal state.
        """
        on_msg = _capture_on_message()
        on_msg(None, _order_event(111, "FILLED", side="SELL", orig_qty=1.0, executed_qty=1.0))
        on_msg(None, _order_event(222, "NEW",    side="BUY"))
        with _state_mod.state_lock:
            s = dict(_state_mod.placing_order_state)
        assert s["order_id"] == 222
        assert s["status"] == "NEW"
        assert s["side"] == "BUY"

    def test_is_clean_resets_to_false_when_order2_arrives_new(self):
        """
        Regression: is_clean must flip back to False for Order 2's NEW event
        even though Order 1 left it True (FILLED is a terminal status).
        """
        on_msg = _capture_on_message()
        # Order 1 → FILLED leaves is_clean=True
        on_msg(None, _order_event(111, "FILLED", orig_qty=1.0, executed_qty=1.0))
        with _state_mod.state_lock:
            assert _state_mod.placing_order_state["is_clean"] is True
        # Order 2 → NEW must flip is_clean back to False
        on_msg(None, _order_event(222, "NEW"))
        with _state_mod.state_lock:
            assert _state_mod.placing_order_state["is_clean"] is False

    # --- force_position_fetch / per-order status tracking ---

    def test_force_position_fetch_set_on_status_change(self):
        on_msg = _capture_on_message()
        _state_mod.force_position_fetch = False
        on_msg(None, _order_event(111, "NEW"))
        with _state_mod.state_lock:
            assert _state_mod.force_position_fetch is True

    def test_force_position_fetch_set_for_order2_after_order1_evicted(self):
        """
        After Order 1 is FILLED (and evicted from the internal order_status dict),
        Order 2's first event must be seen as None→NEW — a genuine status change —
        and must set force_position_fetch.

        Without per-order-id tracking the handler would have mis-read this as a
        spurious FILLED→NEW transition on the same logical order.
        """
        on_msg = _capture_on_message()
        on_msg(None, _order_event(111, "FILLED", orig_qty=1.0, executed_qty=1.0))
        with _state_mod.state_lock:
            _state_mod.force_position_fetch = False  # clear so Order 2's change is detectable

        on_msg(None, _order_event(222, "NEW"))
        with _state_mod.state_lock:
            assert _state_mod.force_position_fetch is True

    def test_same_status_repeat_does_not_retrigger_force_position_fetch(self):
        """Duplicate events for the same order and status must not re-set the flag."""
        on_msg = _capture_on_message()
        on_msg(None, _order_event(111, "NEW"))
        with _state_mod.state_lock:
            _state_mod.force_position_fetch = False
        on_msg(None, _order_event(111, "NEW"))   # identical — no change
        with _state_mod.state_lock:
            assert _state_mod.force_position_fetch is False

    # --- filtering ---

    def test_different_symbol_is_ignored(self):
        on_msg = _capture_on_message(symbol="XAUUSDT")
        on_msg(None, _order_event(999, "NEW", symbol="BTCUSDT"))
        with _state_mod.state_lock:
            assert _state_mod.placing_order_state["order_id"] is None

    def test_non_order_trade_update_event_is_ignored(self):
        on_msg = _capture_on_message()
        on_msg(None, json.dumps({"e": "ACCOUNT_UPDATE"}))
        with _state_mod.state_lock:
            assert _state_mod.placing_order_state["order_id"] is None

    # --- fill_pct ---

    def test_fill_pct_for_partial_fill(self):
        on_msg = _capture_on_message()
        on_msg(None, _order_event(111, "PARTIALLY_FILLED", orig_qty=4.0, executed_qty=1.0))
        with _state_mod.state_lock:
            assert _state_mod.placing_order_state["fill_pct"] == 25.0

    # --- terminal statuses ---

    @pytest.mark.parametrize("status", [
        "FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH",
    ])
    def test_terminal_status_sets_is_clean_true(self, status):
        on_msg = _capture_on_message()
        executed = 1.0 if status == "FILLED" else 0.0
        on_msg(None, _order_event(111, status, orig_qty=1.0, executed_qty=executed))
        with _state_mod.state_lock:
            assert _state_mod.placing_order_state["is_clean"] is True
