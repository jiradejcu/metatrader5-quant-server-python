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
# constants
# ---------------------------------------------------------------------------

SYMBOL = "XAUUSDT"
CONTRACT_SIZE = 100
MIN_TRADE = 1

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _order_snapshot(status=None, side=None, order_id=None,
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
    _gb.last_handled_fill_order_id = None
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

    def test_sell_zone_returns_sell_target(self):
        snapshot = _order_snapshot()
        target = _gb._compute_target('SELL', snapshot, 1.0, remaining_capacity=5.0)
        assert target == ('SELL', 1.0)

    def test_buy_zone_returns_buy_target(self):
        snapshot = _order_snapshot()
        target = _gb._compute_target('BUY', snapshot, 1.0, remaining_capacity=5.0)
        assert target == ('BUY', 1.0)

    def test_capacity_exhausted_returns_none(self):
        snapshot = _order_snapshot()
        assert _gb._compute_target('SELL', snapshot, 1.0, remaining_capacity=0.0) is None
        assert _gb._compute_target('BUY',  snapshot, 1.0, remaining_capacity=-1.0) is None

    def test_neutral_no_fill_returns_none(self):
        snapshot = _order_snapshot(status='NEW', side='SELL', order_id='X1')
        assert _gb._compute_target('NEUTRAL', snapshot, 1.0, remaining_capacity=5.0) is None

    def test_neutral_filled_sell_returns_buy_hedge(self):
        snapshot = _order_snapshot(status='FILLED', side='SELL', order_id='S1')
        _gb.last_handled_fill_order_id = None
        target = _gb._compute_target('NEUTRAL', snapshot, 1.0, remaining_capacity=5.0)
        assert target == ('BUY', 1.0)

    def test_neutral_filled_buy_returns_sell_hedge(self):
        snapshot = _order_snapshot(status='FILLED', side='BUY', order_id='B1')
        _gb.last_handled_fill_order_id = None
        target = _gb._compute_target('NEUTRAL', snapshot, 1.0, remaining_capacity=5.0)
        assert target == ('SELL', 1.0)

    def test_neutral_fill_already_handled_returns_none(self):
        snapshot = _order_snapshot(status='FILLED', side='SELL', order_id='S1')
        _gb.last_handled_fill_order_id = 'S1'
        assert _gb._compute_target('NEUTRAL', snapshot, 1.0, remaining_capacity=5.0) is None

    def test_neutral_filled_but_capacity_exhausted_returns_none(self):
        snapshot = _order_snapshot(status='FILLED', side='SELL', order_id='S1')
        _gb.last_handled_fill_order_id = None
        assert _gb._compute_target('NEUTRAL', snapshot, 1.0, remaining_capacity=0.0) is None


# ---------------------------------------------------------------------------
# _reconcile
# ---------------------------------------------------------------------------

class TestReconcile:

    def test_target_none_no_open_orders_does_nothing(self):
        with patch.object(_gb, "cancel_all_open_orders") as mock_cancel, \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._reconcile(SYMBOL, None, [])
        mock_cancel.assert_not_called()
        mock_chase.assert_not_called()

    def test_target_none_with_open_orders_cancels(self):
        with patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._reconcile(SYMBOL, None, [_open_order()])
        mock_cancel.assert_called_once_with(SYMBOL)

    def test_target_set_no_open_orders_chases_new(self):
        mock_resp = SimpleNamespace(order_id="NEW1")
        with patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._reconcile(SYMBOL, ('SELL', 1.0), [])
        mock_chase.assert_called_once_with(SYMBOL, 1.0, 'SELL')

    def test_target_set_wrong_side_cancels(self):
        buy_order = _open_order(side='BUY', price=1500.0)
        with patch.object(_gb, "cancel_all_open_orders") as mock_cancel, \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._reconcile(SYMBOL, ('SELL', 1.0), [buy_order])
        mock_cancel.assert_called_once_with(SYMBOL)
        mock_chase.assert_not_called()

    def test_target_set_right_side_chases(self):
        sell_order = _open_order(side='SELL', price=1800.0, orig_qty=1.0)
        with patch.object(_gb, "chase_order") as mock_chase:
            _gb._reconcile(SYMBOL, ('SELL', 1.0), [sell_order])
        mock_chase.assert_called_once_with(SYMBOL, 1.0, 'SELL')


# ---------------------------------------------------------------------------
# _process_tick
# ---------------------------------------------------------------------------

class TestProcessTick:

    def _run(self, snapshot, open_orders, position_amt,
             upper_limit=10.0, lower_limit=-10.0,
             max_pos=5.0, order_size=1.0,
             current_upper_diff=0.0, current_lower_diff=0.0):
        with patch.object(_gb, "get_open_orders", return_value=open_orders), \
             patch.object(_gb, "get_position", return_value=_position(position_amt)):
            _gb._process_tick(
                SYMBOL, snapshot,
                CONTRACT_SIZE, MIN_TRADE,
                upper_limit, lower_limit, max_pos, order_size,
                current_upper_diff, current_lower_diff,
            )

    # --- sell / buy zone ---

    def test_sell_zone_places_new_order(self):
        snapshot = _order_snapshot()
        mock_resp = SimpleNamespace(order_id="S1")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=6.0, current_lower_diff=0.0,
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "SELL")

    def test_buy_zone_places_new_order(self):
        snapshot = _order_snapshot()
        mock_resp = SimpleNamespace(order_id="B1")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=0.0, current_lower_diff=-6.0,
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "BUY")

    def test_sell_zone_chases_existing_order(self):
        """Open SELL already exists → chase it."""
        snapshot = _order_snapshot(status="NEW", side="SELL")
        sell_order = _open_order(side="SELL", price=1800.0, orig_qty=1.0)
        with patch.object(_gb, "get_open_orders", return_value=[sell_order]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=6.0, current_lower_diff=0.0,
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "SELL")

    def test_buy_zone_chases_existing_order(self):
        """Open BUY already exists → chase it."""
        snapshot = _order_snapshot(status="NEW", side="BUY")
        buy_order = _open_order(side="BUY", price=1000.0, orig_qty=1.0)
        with patch.object(_gb, "get_open_orders", return_value=[buy_order]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=0.0, current_lower_diff=-6.0,
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "BUY")

    def test_sell_zone_wrong_side_open_order_cancels(self):
        """In SELL zone with a BUY open order → cancel (wrong side), re-place next tick."""
        snapshot = _order_snapshot()
        buy_order = _open_order(side="BUY", price=2000.0, orig_qty=1.0)
        with patch.object(_gb, "get_open_orders", return_value=[buy_order]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel, \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=6.0, current_lower_diff=0.0,
            )
        mock_cancel.assert_called_once_with(SYMBOL)
        mock_chase.assert_not_called()

    def test_sell_zone_capacity_exceeded_cancels(self):
        """Position already at max → capacity ≤ 0 → target=None → cancel."""
        snapshot = _order_snapshot()
        sell_order = _open_order(side="SELL", price=2500.0, orig_qty=5.0)
        with patch.object(_gb, "get_open_orders", return_value=[sell_order]), \
             patch.object(_gb, "get_position", return_value=_position(-5.0)), \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=6.0, current_lower_diff=0.0,
            )
        mock_cancel.assert_called_once_with(SYMBOL)

    def test_capacity_zero_with_pending_order_cancels(self):
        """Pending buy=5 fills capacity (max=5) → target=None → cancel."""
        snapshot = _order_snapshot()
        buy_order = _open_order(side="BUY", price=2000.0, orig_qty=5.0)
        with patch.object(_gb, "get_open_orders", return_value=[buy_order]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel, \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=6.0, current_lower_diff=0.0,
            )
        mock_cancel.assert_called_once_with(SYMBOL)
        mock_chase.assert_not_called()

    # --- neutral zone ---

    def test_neutral_no_orders_no_action(self):
        """Neutral zone, no open orders, no pending fill → nothing."""
        snapshot = _order_snapshot(status=None)
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order") as mock_chase, \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=3.0, current_lower_diff=-3.0,
            )
        mock_chase.assert_not_called()
        mock_cancel.assert_not_called()

    def test_neutral_with_unfilled_open_order_cancels(self):
        """Neutral zone, open order still sitting → cancel it."""
        snapshot = _order_snapshot(status='NEW', side='SELL', order_id='S1')
        sell_order = _open_order(side='SELL', price=2501.0, orig_qty=1.0)
        with patch.object(_gb, "get_open_orders", return_value=[sell_order]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=2.0, current_lower_diff=-2.0,
            )
        mock_cancel.assert_called_once_with(SYMBOL)

    def test_neutral_after_sell_filled_places_buy_hedge(self):
        """Neutral zone, last SELL was filled → place BUY hedge."""
        snapshot = _order_snapshot(status='FILLED', side='SELL', order_id='S1')
        _gb.last_handled_fill_order_id = None
        mock_resp = SimpleNamespace(order_id="HEDGE1")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=2.0, current_lower_diff=-2.0,
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "BUY")

    def test_neutral_after_buy_filled_places_sell_hedge(self):
        """Neutral zone, last BUY was filled → place SELL hedge."""
        snapshot = _order_snapshot(status='FILLED', side='BUY', order_id='B1')
        _gb.last_handled_fill_order_id = None
        mock_resp = SimpleNamespace(order_id="HEDGE2")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=2.0, current_lower_diff=-2.0,
            )
        mock_chase.assert_called_once_with(SYMBOL, 1.0, "SELL")

    def test_neutral_fill_already_handled_no_duplicate_hedge(self):
        """Already hedged this fill → do not place another order."""
        snapshot = _order_snapshot(status='FILLED', side='SELL', order_id='S1')
        _gb.last_handled_fill_order_id = 'S1'
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order") as mock_chase:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=2.0, current_lower_diff=-2.0,
            )
        mock_chase.assert_not_called()

    def test_neutral_hedge_sets_last_handled_fill_order_id(self):
        """After hedging fill S1, last_handled should be the hedge order ID."""
        snapshot = _order_snapshot(status='FILLED', side='SELL', order_id='S1')
        _gb.last_handled_fill_order_id = None
        mock_resp = SimpleNamespace(order_id="HEDGE1")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp):
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=2.0, current_lower_diff=-2.0,
            )
        assert _gb.last_handled_fill_order_id == "HEDGE1"

    def test_zone_order_does_not_set_last_handled(self):
        """Zone orders (SELL/BUY zone) must not touch last_handled_fill_order_id."""
        _gb.last_handled_fill_order_id = "OLD"
        snapshot = _order_snapshot(status='FILLED', order_id='S1')
        mock_resp = SimpleNamespace(order_id="NEW1")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.0)), \
             patch.object(_gb, "chase_order", return_value=mock_resp):
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=6.0, current_lower_diff=0.0,
            )
        assert _gb.last_handled_fill_order_id == "OLD"

    # --- fractional position ---

    def test_fractional_position_places_new_sell_order(self):
        """position_amt=0.5 → unfilled fractional → chase new order."""
        snapshot = _order_snapshot(status="FILLED", side="SELL")
        mock_resp = SimpleNamespace(order_id="F1")
        with patch.object(_gb, "get_open_orders", return_value=[]), \
             patch.object(_gb, "get_position", return_value=_position(0.5)), \
             patch.object(_gb, "chase_order", return_value=mock_resp) as mock_chase:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=0.0, current_lower_diff=0.0,
            )
        assert mock_chase.call_count == 1
        assert mock_chase.call_args[0][2] == "SELL"

    def test_fractional_position_chases_existing_order(self):
        """Fractional + open order → chase it."""
        snapshot = _order_snapshot(status="NEW", side="SELL")
        sell_order = _open_order(side="SELL", price=2500.0, orig_qty=0.5)
        with patch.object(_gb, "get_open_orders", return_value=[sell_order]), \
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
             patch.object(_gb, "get_position", return_value=_position(-5.5)), \
             patch.object(_gb, "cancel_all_open_orders") as mock_cancel:
            _gb._process_tick(
                SYMBOL, snapshot, CONTRACT_SIZE, MIN_TRADE,
                upper_limit=5.0, lower_limit=-5.0,
                max_pos=5.0, order_size=1.0,
                current_upper_diff=0.0, current_lower_diff=0.0,
            )
        mock_cancel.assert_called_once_with(SYMBOL)

    # --- _record_new_order side effects ---

    def test_record_new_order_sets_last_acted_order_id(self):
        mock_resp = SimpleNamespace(order_id="REC1")
        _gb._record_new_order(mock_resp)
        assert _gb.last_acted_order_id == "REC1"
        assert _gb.optimistic_dirty_time > 0

    def test_record_new_order_does_not_clear_last_handled_fill_order_id(self):
        _gb.last_handled_fill_order_id = "OLD"
        _gb._record_new_order(SimpleNamespace(order_id="NEW1"))
        assert _gb.last_handled_fill_order_id == "OLD"

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
