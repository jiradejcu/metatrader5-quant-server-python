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

# --- config: load PAIRS directly from the real config.py ---
_config_mod = types.ModuleType(f"{_PKG}.config")
_real_config_path = pathlib.Path(__file__).parent.parent / "config.py"
_real_config_spec = importlib.util.spec_from_file_location("_real_config", _real_config_path)
_real_config = importlib.util.module_from_spec(_real_config_spec)
_real_config_spec.loader.exec_module(_real_config)
_config_mod.PAIRS = _real_config.PAIRS
sys.modules[f"{_PKG}.config"] = _config_mod

# --- price_diff stub ---
_price_diff_mod = types.ModuleType(f"{_PKG}.price_diff")
_price_diff_mod.PRICE_DIFF_MAX_AGE_MS = int(
    __import__("os").getenv("PRICE_DIFF_MAX_AGE_MS", "1600")
)
sys.modules[f"{_PKG}.price_diff"] = _price_diff_mod

# --- minimal state stub (mirrors the real state.py) ---
_state_mod = types.ModuleType(f"{_PKG}.state")
_state_mod.state_lock = threading.Lock()
_state_mod.placing_order_state = {
    "order_id": None, "status": None, "is_clean": True,
    "fill_pct": 0, "side": None, "price": None, "orig_qty": 0,
}
_state_mod.force_fetch = False
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
    _state_mod.force_fetch = False
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

    @pytest.fixture(autouse=True)
    def integer_mode(self):
        """Ensure integer truncation mode (no MOCK_ENTRY) for all basic tests."""
        with patch.dict("os.environ", _INTEGER_ENV):
            yield

    def test_sell_zone_returns_position_minus_order_size(self):
        assert _gb._compute_target('SELL', 0.0, 1.0, max_pos=5.0) == -1.0

    def test_sell_zone_with_existing_position(self):
        assert _gb._compute_target('SELL', -1.0, 1.0, max_pos=5.0) == -2.0

    def test_buy_zone_returns_position_plus_order_size(self):
        assert _gb._compute_target('BUY', 0.0, 1.0, max_pos=5.0) == 1.0

    def test_buy_zone_with_existing_position(self):
        assert _gb._compute_target('BUY', 1.0, 1.0, max_pos=5.0) == 2.0

    def test_neutral_returns_current_position(self):
        assert _gb._compute_target('NEUTRAL', 2.0, 1.0, max_pos=5.0) == 2.0

    def test_neutral_flat_returns_zero(self):
        assert _gb._compute_target('NEUTRAL', 0.0, 1.0, max_pos=5.0) == 0.0

    def test_capacity_exhausted_no_pending_returns_current_position(self):
        # max_pos == abs(position_amt): no remaining capacity, hold filled position
        assert _gb._compute_target('SELL', -4.0, 1.0, max_pos=4.0) == -4.0
        # max_pos < abs(position_amt): over-committed, hold position
        assert _gb._compute_target('BUY',   4.0, 1.0, max_pos=3.0) == 4.0

    def test_capacity_exhausted_with_pending_returns_committed_target(self):
        # max_pos == abs(position_amt + net_pending): pending fills the last slot — chase it.
        # Fractional lots only occur in MOCK_ENTRY mode.
        with patch.dict("os.environ", {"MOCK_ENTRY_POSITION_AMT": "true", "PAIR_INDEX": "0"}):
            assert _gb._compute_target('SELL', -0.04, 0.01, max_pos=0.05, net_pending=-0.01) == pytest.approx(-0.05)
            # Same for BUY direction
            assert _gb._compute_target('BUY', 0.04, 0.01, max_pos=0.05, net_pending=0.01) == pytest.approx(0.05)

    def test_over_committed_returns_current_position(self):
        # max_pos < abs(position_amt + net_pending): over-committed — cancel excess order.
        # Fractional lots only occur in MOCK_ENTRY mode.
        with patch.dict("os.environ", {"MOCK_ENTRY_POSITION_AMT": "true", "PAIR_INDEX": "0"}):
            assert _gb._compute_target('SELL', -0.03, 0.01, max_pos=0.03, net_pending=-0.01) == pytest.approx(-0.03)
            assert _gb._compute_target('BUY', 0.03, 0.01, max_pos=0.03, net_pending=0.01) == pytest.approx(0.03)

    def test_neutral_truncates_fractional_position(self):
        # NEUTRAL zone: _trunc applied — fractional position is truncated.
        # Fractional lots only occur in MOCK_ENTRY mode.
        with patch.dict("os.environ", {"MOCK_ENTRY_POSITION_AMT": "true", "PAIR_INDEX": "0"}):
            assert _gb._compute_target('NEUTRAL', -0.03, 0.01, max_pos=0.03) == pytest.approx(-0.03)

    def test_capacity_exhausted_in_neutral_returns_current_position(self):
        assert _gb._compute_target('NEUTRAL', -3.0, 1.0, max_pos=3.0) == -3.0


# ---------------------------------------------------------------------------
# _compute_target — truncation towards zero
# ---------------------------------------------------------------------------

_INTEGER_ENV = {"MOCK_ENTRY_POSITION_AMT": "false"}


class TestComputeTargetTruncation:
    """Target must be truncated towards zero (math.trunc), not floored."""

    # --- BUY zone (positive result) ---

    def test_buy_fractional_position_truncates_down(self):
        # 0.531 + 1.0 = 1.531 → trunc → 1  (not 2)
        with patch.dict("os.environ", _INTEGER_ENV):
            assert _gb._compute_target('BUY', 0.531, 1.0, max_pos=10.0) == 1

    def test_buy_large_fractional_position_truncates(self):
        # real-world case from logs: 287.531 + 1.0 = 288.531 → trunc → 288
        with patch.dict("os.environ", _INTEGER_ENV):
            assert _gb._compute_target('BUY', 287.531, 1.0, max_pos=300.0) == 288

    def test_buy_result_near_zero_truncates_to_zero(self):
        # -0.8 + 1.0 = 0.2 → trunc → 0
        with patch.dict("os.environ", _INTEGER_ENV):
            assert _gb._compute_target('BUY', -0.8, 1.0, max_pos=5.0) == 0

    # --- SELL zone (negative result) ---

    def test_sell_fractional_position_truncates_towards_zero(self):
        # -0.531 - 1.0 = -1.531 → trunc → -1  (not -2, which floor would give)
        with patch.dict("os.environ", _INTEGER_ENV):
            assert _gb._compute_target('SELL', -0.531, 1.0, max_pos=10.0) == -1

    def test_sell_large_fractional_position_truncates_towards_zero(self):
        # -287.531 - 1.0 = -288.531 → trunc → -288  (not -289)
        with patch.dict("os.environ", _INTEGER_ENV):
            assert _gb._compute_target('SELL', -287.531, 1.0, max_pos=300.0) == -288

    def test_sell_result_near_zero_truncates_to_zero(self):
        # 0.8 - 1.0 = -0.2 → trunc → 0  (not -1 which floor would give)
        with patch.dict("os.environ", _INTEGER_ENV):
            assert _gb._compute_target('SELL', 0.8, 1.0, max_pos=5.0) == 0

    # --- trunc vs floor distinction ---

    def test_trunc_differs_from_floor_for_negative(self):
        # This is the key property: trunc(-1.531)==-1, floor(-1.531)==-2
        with patch.dict("os.environ", _INTEGER_ENV):
            result = _gb._compute_target('SELL', -0.531, 1.0, max_pos=10.0)
        assert result == -1, f"Expected -1 (trunc), got {result} (floor would give -2)"

    # --- whole numbers are unaffected ---

    def test_whole_number_buy_unchanged(self):
        with patch.dict("os.environ", _INTEGER_ENV):
            assert _gb._compute_target('BUY', 0.0, 1.0, max_pos=5.0) == 1

    def test_whole_number_sell_unchanged(self):
        with patch.dict("os.environ", _INTEGER_ENV):
            assert _gb._compute_target('SELL', 0.0, 1.0, max_pos=5.0) == -1


# ---------------------------------------------------------------------------
# _compute_target — MOCK_ENTRY_POSITION_AMT truncation
# ---------------------------------------------------------------------------

_MOCK_ENV = {"MOCK_ENTRY_POSITION_AMT": "true", "PAIR_INDEX": "0"}  # contract_size=100


class TestComputeTargetContractSize:
    """
    In MOCK_ENTRY_POSITION_AMT mode the target is truncated to the nearest
    1/contract_size lot (trunc(val * contract_size) / contract_size) instead
    of the nearest integer. contract_size comes from config.PAIRS[PAIR_INDEX].
    """

    # --- BUY zone ---

    def test_buy_exact_lot_unchanged(self):
        # 0 + 0.01 = 0.01 → trunc(0.01 × 100)/100 = trunc(1.0)/100 = 0.01
        with patch.dict("os.environ", _MOCK_ENV):
            assert _gb._compute_target('BUY', 0.0, 0.01, 5.0) == pytest.approx(0.01)

    def test_buy_fractional_lot_truncated_down(self):
        # 0 + 0.012 = 0.012 → trunc(1.2)/100 = 0.01   (not 0.02)
        with patch.dict("os.environ", _MOCK_ENV):
            assert _gb._compute_target('BUY', 0.0, 0.012, 5.0) == pytest.approx(0.01)

    def test_buy_accumulates_with_existing_position(self):
        # 0.01 + 0.01 = 0.02 → trunc(2.0)/100 = 0.02
        with patch.dict("os.environ", _MOCK_ENV):
            assert _gb._compute_target('BUY', 0.01, 0.01, 5.0) == pytest.approx(0.02)

    def test_buy_fractional_lot_with_existing_position(self):
        # 0.01 + 0.012 = 0.022 → trunc(2.2)/100 = 0.02
        with patch.dict("os.environ", _MOCK_ENV):
            assert _gb._compute_target('BUY', 0.01, 0.012, 5.0) == pytest.approx(0.02)

    # --- SELL zone ---

    def test_sell_exact_lot_unchanged(self):
        # 0 - 0.01 = -0.01 → trunc(-1.0)/100 = -0.01
        with patch.dict("os.environ", _MOCK_ENV):
            assert _gb._compute_target('SELL', 0.0, 0.01, 5.0) == pytest.approx(-0.01)

    def test_sell_fractional_lot_truncates_towards_zero(self):
        # 0 - 0.012 = -0.012 → trunc(-1.2)/100 = -0.01   (not -0.02)
        with patch.dict("os.environ", _MOCK_ENV):
            assert _gb._compute_target('SELL', 0.0, 0.012, 5.0) == pytest.approx(-0.01)

    def test_sell_accumulates_with_existing_negative_position(self):
        # -0.01 - 0.01 = -0.02 → trunc(-2.0)/100 = -0.02
        with patch.dict("os.environ", _MOCK_ENV):
            assert _gb._compute_target('SELL', -0.01, 0.01, 5.0) == pytest.approx(-0.02)

    def test_sell_fractional_lot_with_existing_negative_position(self):
        # -0.01 - 0.012 = -0.022 → trunc(-2.2)/100 = -0.02
        with patch.dict("os.environ", _MOCK_ENV):
            assert _gb._compute_target('SELL', -0.01, 0.012, 5.0) == pytest.approx(-0.02)

    # --- NEUTRAL / capacity exhausted ---

    def test_neutral_returns_position_unchanged(self):
        with patch.dict("os.environ", _MOCK_ENV):
            assert _gb._compute_target('NEUTRAL', 0.05, 0.01, 5.0) == pytest.approx(0.05)

    def test_capacity_exhausted_returns_position_unchanged(self):
        with patch.dict("os.environ", _MOCK_ENV):
            assert _gb._compute_target('BUY', 0.05, 0.01, 0.0) == pytest.approx(0.05)

    # --- without MOCK_ENTRY — integer truncation ---

    def test_without_mock_entry_buy_integer_trunc(self):
        with patch.dict("os.environ", {"MOCK_ENTRY_POSITION_AMT": "false"}):
            assert _gb._compute_target('BUY', 0.0, 1.0, 5.0) == 1

    def test_without_mock_entry_sell_integer_trunc(self):
        with patch.dict("os.environ", {"MOCK_ENTRY_POSITION_AMT": "false"}):
            assert _gb._compute_target('SELL', 0.0, 1.0, 5.0) == -1


# ---------------------------------------------------------------------------
# _compute_target — opposite-direction (closing) branch
# ---------------------------------------------------------------------------

class TestComputeTargetOppositeDirection:
    """Covers the branch where the order reduces an existing position (position_amt * zone_delta < 0).

    The fix changed the clamp from the symmetric max(-max_pos, raw) to
    direction-aware: BUY uses min(raw, +max_pos), SELL uses max(raw, -max_pos).
    """

    @pytest.fixture(autouse=True)
    def integer_mode(self):
        with patch.dict("os.environ", _INTEGER_ENV):
            yield

    def test_short_buy_max_pos_zero_is_incremental(self):
        # Bug repro: position=-170, max_pos=0, order_size=10, zone=BUY.
        # Old: max(-0.0, -170+10) = max(0, -160) = 0  → reconcile places 170-lot BUY.
        # Fixed: min(-170+10, 0.0) = min(-160, 0) = -160 → incremental 10-lot BUY.
        assert _gb._compute_target('BUY', -170.0, 10.0, max_pos=0.0) == -160

    def test_long_sell_max_pos_zero_is_incremental(self):
        # Symmetric: position=+170, max_pos=0, order_size=10, zone=SELL.
        # max(+170-10, -0.0) = max(+160, 0) = +160 → incremental 10-lot SELL. (was correct)
        assert _gb._compute_target('SELL', 170.0, 10.0, max_pos=0.0) == 160

    def test_short_buy_clamps_at_positive_max_pos(self):
        # position=-10, order_size=20, max_pos=5 → raw=+10 overshoots.
        # min(+10, 5) = 5; diff = 5-(-10) = 15-lot BUY (capped).
        assert _gb._compute_target('BUY', -10.0, 20.0, max_pos=5.0) == 5

    def test_long_sell_clamps_at_negative_max_pos(self):
        # position=+10, order_size=20, max_pos=5 → raw=-10 overshoots.
        # max(-10, -5) = -5; diff = -5-(+10) = 15-lot SELL (capped).
        assert _gb._compute_target('SELL', 10.0, 20.0, max_pos=5.0) == -5

    def test_short_buy_exactly_crosses_zero_clamps_to_zero(self):
        # position=-5, order_size=10, max_pos=0 → raw=+5, clamp to min(5, 0)=0.
        assert _gb._compute_target('BUY', -5.0, 10.0, max_pos=0.0) == 0

    def test_short_buy_does_not_overshoot_when_raw_stays_negative(self):
        # position=-20, order_size=10, max_pos=15 → raw=-10, no clamping needed.
        assert _gb._compute_target('BUY', -20.0, 10.0, max_pos=15.0) == -10

    def test_long_sell_does_not_undershoot_when_raw_stays_positive(self):
        # position=+20, order_size=10, max_pos=15 → raw=+10, no clamping needed.
        assert _gb._compute_target('SELL', 20.0, 10.0, max_pos=15.0) == 10


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

    def test_capacity_zero_with_pending_order_chases(self):
        """Pending buy exactly fills capacity (remaining=0) → chase, don't cancel."""
        buy_order = _open_order(side="BUY", price=2000.0, orig_qty=5.0, order_id=99)
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
        mock_cancel.assert_not_called()
        mock_chase.assert_called_once_with(SYMBOL, 5.0, "BUY", order_id=99)

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
# handle_grid_flow — price diff globals
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


class TestHandleGridFlowPriceDiff:

    def test_fresh_message_updates_globals(self):
        """A price_diff message with a recent ts should update latest_ask/bid_diff."""
        msg = make_price_message(PRICE_CH, 7.5, -3.2, ts=time.time())
        ask, bid = _run_handle_grid_flow_with_messages([msg])
        assert ask == 7.5
        assert bid == -3.2

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


# ---------------------------------------------------------------------------
# ATR computation
# ---------------------------------------------------------------------------

class TestATRComputation:

    def test_first_message_atr_stays_zero(self):
        """No previous value to diff against → ATR remains 0."""
        msg = make_price_message(PRICE_CH, 3.0, 3.2, ts=time.time())
        _run_handle_grid_flow_with_messages([msg])
        assert _gb.latest_atr == 0.0

    def test_second_message_computes_atr_from_ask_delta(self):
        """When ask delta dominates, TR = |Δask|. TR > ATR(=0) → fast (up) alpha."""
        msg1 = make_price_message(PRICE_CH, 1.5, 1.6, ts=time.time())
        msg2 = make_price_message(PRICE_CH, 3.0, 1.7, ts=time.time())  # ask Δ=1.5, bid Δ=0.1
        _run_handle_grid_flow_with_messages([msg1, msg2])
        expected = _gb._ATR_ALPHA_UP * 1.5  # prev ATR was 0
        assert abs(_gb.latest_atr - expected) < 1e-9

    def test_second_message_uses_max_of_ask_and_bid_delta(self):
        """When bid delta dominates, TR = |Δbid|."""
        msg1 = make_price_message(PRICE_CH, 3.0, 1.0, ts=time.time())
        msg2 = make_price_message(PRICE_CH, 3.5, 3.0, ts=time.time())  # ask Δ=0.5, bid Δ=2.0
        _run_handle_grid_flow_with_messages([msg1, msg2])
        expected = _gb._ATR_ALPHA_UP * 2.0
        assert abs(_gb.latest_atr - expected) < 1e-9

    def test_atr_decays_slowly_after_spike(self):
        """After a large spike, calm ticks reduce ATR using the slow-release alpha."""
        msg1 = make_price_message(PRICE_CH, 1.56, 1.69, ts=time.time())
        msg2 = make_price_message(PRICE_CH, 4.29, 4.41, ts=time.time())  # spike: ask Δ=2.73
        msg3 = make_price_message(PRICE_CH, 4.30, 4.42, ts=time.time())  # calm: Δ=0.01
        msg4 = make_price_message(PRICE_CH, 4.31, 4.43, ts=time.time())  # calm: Δ=0.01
        _run_handle_grid_flow_with_messages([msg1, msg2, msg3, msg4])

        atr_spike  = _gb._ATR_ALPHA_UP * 2.73
        atr_calm1  = _gb._ATR_ALPHA_DOWN * 0.01 + (1 - _gb._ATR_ALPHA_DOWN) * atr_spike
        atr_calm2  = _gb._ATR_ALPHA_DOWN * 0.01 + (1 - _gb._ATR_ALPHA_DOWN) * atr_calm1
        assert abs(_gb.latest_atr - atr_calm2) < 1e-6
        assert _gb.latest_atr < atr_spike
        # Slow release: decay alpha is much smaller than the rise alpha.
        assert _gb._ATR_ALPHA_DOWN < _gb._ATR_ALPHA_UP

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
        msg2 = make_price_message(PRICE_CH, 3.1, 3.2, ts=time.time())  # Δ=0.1 → ATR ≈ 0.025
        assert _run_handle_grid_flow_active([msg1, msg2]) is True

    def test_process_tick_blocked_when_atr_high(self):
        """1.56→4.29 spike raises ATR above threshold → _process_tick is NOT called."""
        msg1 = make_price_message(PRICE_CH, 1.56, 1.69, ts=time.time())
        msg2 = make_price_message(PRICE_CH, 4.29, 4.41, ts=time.time())  # ATR ≈ 0.6825
        assert _run_handle_grid_flow_active([msg1, msg2]) is False

    def test_atr_decay_is_slow_after_spike(self):
        """
        Asymmetric EMA (period=7 up, period_down=28 down): ATR rises fast on a
        spike but decays slowly afterward, so the guard stays blocked well
        beyond the first calm tick.
          spike        → ATR≈0.683  blocked
          spike+calm×1 → ATR≈0.636  still blocked
          spike+calm×2 → ATR≈0.593  still blocked
        Each call replays from scratch so ATR is built fresh from the message sequence.
        Messages omit ts to avoid the stale-price-diff filter across the sequential calls.
        """
        def msgs(*price_pairs):
            return [make_price_message(PRICE_CH, ask, bid) for ask, bid in price_pairs]

        # (ask, bid) sequence: baseline → spike → calm ticks
        baseline = (1.56, 1.69)
        spike    = (4.29, 4.41)  # Δ=2.73 → ATR≈0.683
        calm1    = (4.30, 4.42)  # Δ=0.01 → ATR≈0.636
        calm2    = (4.31, 4.43)  # Δ=0.01 → ATR≈0.593

        assert _run_handle_grid_flow_active(msgs(baseline, spike)) is False, \
            "spike should block immediately"
        assert _run_handle_grid_flow_active(msgs(baseline, spike, calm1)) is False, \
            "slow-release alpha means one calm tick barely reduces ATR"
        assert _run_handle_grid_flow_active(msgs(baseline, spike, calm1, calm2)) is False, \
            "two calm ticks still aren't enough to drop ATR below threshold"


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
    import app.connectors.binance.api.user_data_stream as _uds

    captured: dict = {}

    class _FakeWSApp:
        def __init__(self, url, on_open=None, on_message=None,
                     on_error=None, on_close=None):
            captured["on_message"] = on_message

        def run_forever(self, **kwargs):
            raise _StopUserStream()

    fake_stream = MagicMock()
    fake_stream.data.return_value.listen_key = "test_key"
    redis_mock = MagicMock()

    def _on_order_update(update):
        with _state_mod.state_lock:
            _state_mod.placing_order_state.update({k: v for k, v in update.items() if k != 'status_changed'})
            if update['status_changed']:
                _state_mod.force_fetch = True

    with patch.object(_uds.binance_client.rest_api, "start_user_data_stream",
                      return_value=fake_stream), \
         patch.object(_uds.websocket, "WebSocketApp", _FakeWSApp), \
         patch.object(_uds, "get_redis_connection", return_value=redis_mock):
        try:
            _uds.watch_user_data_stream(symbol, on_order_update=_on_order_update)
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
        """Isolate placing_order_state and force_fetch between tests."""
        def _reset():
            _state_mod.placing_order_state.update({
                "order_id": None, "status": None, "is_clean": True,
                "fill_pct": 0, "side": None, "price": None, "orig_qty": 0,
            })
            _state_mod.force_fetch = False

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

    # --- force_fetch / per-order status tracking ---

    def test_force_fetch_set_on_status_change(self):
        on_msg = _capture_on_message()
        _state_mod.force_fetch = False
        on_msg(None, _order_event(111, "NEW"))
        with _state_mod.state_lock:
            assert _state_mod.force_fetch is True

    def test_force_fetch_set_for_order2_after_order1_evicted(self):
        """
        After Order 1 is FILLED (and evicted from the internal order_status dict),
        Order 2's first event must be seen as None→NEW — a genuine status change —
        and must set force_fetch.

        Without per-order-id tracking the handler would have mis-read this as a
        spurious FILLED→NEW transition on the same logical order.
        """
        on_msg = _capture_on_message()
        on_msg(None, _order_event(111, "FILLED", orig_qty=1.0, executed_qty=1.0))
        with _state_mod.state_lock:
            _state_mod.force_fetch = False  # clear so Order 2's change is detectable

        on_msg(None, _order_event(222, "NEW"))
        with _state_mod.state_lock:
            assert _state_mod.force_fetch is True

    def test_same_status_repeat_does_not_retrigger_force_fetch(self):
        """Duplicate events for the same order and status must not re-set the flag."""
        on_msg = _capture_on_message()
        on_msg(None, _order_event(111, "NEW"))
        with _state_mod.state_lock:
            _state_mod.force_fetch = False
        on_msg(None, _order_event(111, "NEW"))   # identical — no change
        with _state_mod.state_lock:
            assert _state_mod.force_fetch is False

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
