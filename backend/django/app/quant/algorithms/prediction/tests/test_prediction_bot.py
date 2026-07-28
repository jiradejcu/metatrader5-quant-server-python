"""
Automated tests for prediction_bot trading logic.

External Binance calls (get_open_orders, get_position, get_ticker,
get_order_book, cancel_all_open_orders, chase_order, close_order) are patched
on the loaded module object.
"""
import importlib.util
import json
import pathlib
import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Load prediction_bot.py under a synthetic package tree so its relative
# imports ("from ..arbitrage import config", "from . import state") resolve
# without needing the full Django app stack.
# ---------------------------------------------------------------------------

_PKG = "_pb_test_pkg"

_root = types.ModuleType(_PKG)
_root.__path__ = []
sys.modules[_PKG] = _root

# --- sibling arbitrage.config, loaded from the real config.py ---
_arbitrage_pkg = types.ModuleType(f"{_PKG}.arbitrage")
_arbitrage_pkg.__path__ = []
sys.modules[f"{_PKG}.arbitrage"] = _arbitrage_pkg

_real_config_path = pathlib.Path(__file__).parents[2] / "arbitrage" / "config.py"
_real_config_spec = importlib.util.spec_from_file_location("_real_config", _real_config_path)
_real_config = importlib.util.module_from_spec(_real_config_spec)
_real_config_spec.loader.exec_module(_real_config)

_config_mod = types.ModuleType(f"{_PKG}.arbitrage.config")
_config_mod.PAIRS = _real_config.PAIRS
sys.modules[f"{_PKG}.arbitrage.config"] = _config_mod
_arbitrage_pkg.config = _config_mod

# --- prediction package + state stub ---
_prediction_pkg = types.ModuleType(f"{_PKG}.prediction")
_prediction_pkg.__path__ = []
sys.modules[f"{_PKG}.prediction"] = _prediction_pkg

_state_mod = types.ModuleType(f"{_PKG}.prediction.state")
import threading as _threading
_state_mod.state_lock = _threading.Lock()
sys.modules[f"{_PKG}.prediction.state"] = _state_mod

# --- load prediction_bot.py as _PKG.prediction.prediction_bot ---
_pb_path = pathlib.Path(__file__).parent.parent / "prediction_bot.py"
_spec = importlib.util.spec_from_file_location(f"{_PKG}.prediction.prediction_bot", str(_pb_path))
_pb = importlib.util.module_from_spec(_spec)
_pb.__package__ = f"{_PKG}.prediction"
sys.modules[f"{_PKG}.prediction.prediction_bot"] = _pb
_spec.loader.exec_module(_pb)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _open_order(side="BUY", orig_qty=1.0, order_id=123):
    return SimpleNamespace(side=side, orig_qty=orig_qty, order_id=order_id)


def _position(position_amt="0", entry_price="0"):
    return {"positionAmt": position_amt, "entryPrice": entry_price}


DEFAULT_SETTINGS = {
    "minutes_before_close": 15.0,
    "order_amount": 1.0,
    "profit_target_usd": 5.0,
    "max_slippage_usd": 2.0,
}


@pytest.fixture(autouse=True)
def reset_globals():
    _pb.latest_prediction_settings = None
    yield
    _pb.latest_prediction_settings = None


# ---------------------------------------------------------------------------
# _parse_prediction_settings
# ---------------------------------------------------------------------------

class TestParsePredictionSettings:
    def test_parses_all_fields(self):
        raw = {
            "minutes_before_close": "10",
            "order_amount": "2.5",
            "profit_target_usd": "3",
            "max_slippage_usd": "1.5",
        }
        parsed = _pb._parse_prediction_settings(raw)
        assert parsed == {
            "minutes_before_close": 10.0,
            "order_amount": 2.5,
            "profit_target_usd": 3.0,
            "max_slippage_usd": 1.5,
        }

    def test_defaults_missing_fields_to_zero(self):
        assert _pb._parse_prediction_settings({}) == {
            "minutes_before_close": 0.0,
            "order_amount": 0.0,
            "profit_target_usd": 0.0,
            "max_slippage_usd": 0.0,
        }


# ---------------------------------------------------------------------------
# _minutes_until_session_close / _is_entry_window
# ---------------------------------------------------------------------------

class TestMinutesUntilSessionClose:
    def test_no_sessions_returns_none(self):
        assert _pb._minutes_until_session_close(None, datetime(2024, 1, 1, tzinfo=timezone.utc)) is None

    def test_within_active_range_returns_remaining_minutes(self):
        sessions = {"Monday": [{"start": "08:00", "end": "16:00"}]}
        now = datetime(2024, 1, 1, 15, 45, tzinfo=timezone.utc)  # Monday
        assert _pb._minutes_until_session_close(sessions, now) == pytest.approx(15.0)

    def test_outside_any_range_returns_none(self):
        sessions = {"Monday": [{"start": "08:00", "end": "16:00"}]}
        now = datetime(2024, 1, 1, 20, 0, tzinfo=timezone.utc)
        assert _pb._minutes_until_session_close(sessions, now) is None

    def test_end_of_day_marker(self):
        sessions = {"Monday": [{"start": "00:00", "end": "24:00"}]}
        now = datetime(2024, 1, 1, 23, 50, tzinfo=timezone.utc)
        assert _pb._minutes_until_session_close(sessions, now) == pytest.approx(10.0)


class TestIsEntryWindow:
    def test_within_window(self):
        assert _pb._is_entry_window(10.0, 15.0) is True

    def test_outside_window(self):
        assert _pb._is_entry_window(30.0, 15.0) is False

    def test_none_minutes_remaining(self):
        assert _pb._is_entry_window(None, 15.0) is False

    def test_zero_minutes_before_close_disables_entry(self):
        assert _pb._is_entry_window(0.0, 0.0) is False


# ---------------------------------------------------------------------------
# _max_closeable_qty
# ---------------------------------------------------------------------------

class TestMaxCloseableQty:
    def test_empty_book_returns_zero(self):
        assert _pb._max_closeable_qty([], 5.0, 10.0) == (0.0, None)

    def test_full_close_within_first_level(self):
        bids = [(100.0, 10.0), (99.0, 10.0)]
        qty, price = _pb._max_closeable_qty(bids, 5.0, 1.0)
        assert qty == pytest.approx(5.0)
        assert price == 100.0

    def test_close_across_multiple_levels_within_budget(self):
        # best=100, level2=99 costs 1/unit. remaining_qty=15, budget=5 → can
        # take all 10 at level1 (free) + 5 at level2 (5 slippage) = 15 exactly.
        bids = [(100.0, 10.0), (99.0, 20.0)]
        qty, price = _pb._max_closeable_qty(bids, 15.0, 5.0)
        assert qty == pytest.approx(15.0)
        assert price == 99.0

    def test_budget_caps_qty_before_full_position(self):
        bids = [(100.0, 10.0), (99.0, 20.0)]
        qty, price = _pb._max_closeable_qty(bids, 100.0, 5.0)
        assert qty == pytest.approx(15.0)
        assert price == 99.0

    def test_budget_exhausted_at_best_price_only(self):
        bids = [(100.0, 2.0), (95.0, 100.0)]
        qty, price = _pb._max_closeable_qty(bids, 100.0, 1.0)
        # 2 units free at best price, then budget=1 allows 1/(100-95)=0.2 more
        assert qty == pytest.approx(2.2)
        assert price == 95.0


# ---------------------------------------------------------------------------
# _process_tick state machine
# ---------------------------------------------------------------------------

class TestProcessTickIdle:
    def test_enters_within_window_when_not_already_entered(self):
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "_already_entered_today", return_value=False), \
             patch.object(_pb, "_get_trading_sessions", return_value={"x": []}), \
             patch.object(_pb, "_minutes_until_session_close", return_value=5.0), \
             patch.object(_pb, "chase_order") as mock_chase, \
             patch.object(_pb, "_mark_entered_today") as mock_mark:
            _pb._process_tick("BTCUSDT", "XAUUSD", DEFAULT_SETTINGS)
            mock_chase.assert_called_once_with("BTCUSDT", DEFAULT_SETTINGS["order_amount"], "BUY", order_id=None)
            mock_mark.assert_called_once_with("BTCUSDT", "XAUUSD")

    def test_skips_when_already_entered_today(self):
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "_already_entered_today", return_value=True), \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", "XAUUSD", DEFAULT_SETTINGS)
            mock_chase.assert_not_called()

    def test_skips_outside_window(self):
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "_already_entered_today", return_value=False), \
             patch.object(_pb, "_get_trading_sessions", return_value=None), \
             patch.object(_pb, "_minutes_until_session_close", return_value=None), \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", "XAUUSD", DEFAULT_SETTINGS)
            mock_chase.assert_not_called()

    def test_skips_when_order_amount_unset(self):
        settings = dict(DEFAULT_SETTINGS, order_amount=0.0)
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", "XAUUSD", settings)
            mock_chase.assert_not_called()


class TestProcessTickEntering:
    def test_chases_existing_buy_order(self):
        order = _open_order(side="BUY", orig_qty=1.0, order_id=42)
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[order]), \
             patch.object(_pb, "_minutes_until_session_close", return_value=5.0), \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", "XAUUSD", DEFAULT_SETTINGS)
            mock_chase.assert_called_once_with("BTCUSDT", 1.0, "BUY", order_id=42)

    def test_cancels_when_session_ended_before_fill(self):
        order = _open_order(side="BUY")
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[order]), \
             patch.object(_pb, "_minutes_until_session_close", return_value=None), \
             patch.object(_pb, "cancel_all_open_orders") as mock_cancel, \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", "XAUUSD", DEFAULT_SETTINGS)
            mock_cancel.assert_called_once_with("BTCUSDT")
            mock_chase.assert_not_called()

    def test_cancels_unexpected_sell_order(self):
        order = _open_order(side="SELL")
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[order]), \
             patch.object(_pb, "_minutes_until_session_close", return_value=5.0), \
             patch.object(_pb, "cancel_all_open_orders") as mock_cancel:
            _pb._process_tick("BTCUSDT", "XAUUSD", DEFAULT_SETTINGS)
            mock_cancel.assert_called_once_with("BTCUSDT")


class TestProcessTickHolding:
    def test_holds_when_profit_below_target(self):
        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 103.0, "best_ask": 103.5}), \
             patch.object(_pb, "close_order") as mock_close:
            _pb._process_tick("BTCUSDT", "XAUUSD", DEFAULT_SETTINGS)  # target=5.0
            mock_close.assert_not_called()

    def test_closes_when_profit_target_hit_and_depth_sufficient(self):
        order_book = {"bids": [(105.0, 2.0)], "asks": []}
        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 106.0, "best_ask": 106.5}), \
             patch.object(_pb, "get_order_book", return_value=order_book), \
             patch.object(_pb, "close_order") as mock_close:
            _pb._process_tick("BTCUSDT", "XAUUSD", DEFAULT_SETTINGS)  # profit=6 >= target=5
            mock_close.assert_called_once_with("BTCUSDT", 1.0, "SELL", 105.0)

    def test_waits_when_book_too_thin_for_slippage_budget(self):
        # best bid far from remaining book — any close would blow the slippage budget.
        order_book = {"bids": [(90.0, 0.0001)], "asks": []}
        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 106.0, "best_ask": 106.5}), \
             patch.object(_pb, "get_order_book", return_value=order_book), \
             patch.object(_pb, "close_order") as mock_close:
            _pb._process_tick("BTCUSDT", "XAUUSD", DEFAULT_SETTINGS)
            mock_close.assert_not_called()

    def test_skips_unexpected_short_position(self):
        with patch.object(_pb, "get_position", return_value=_position("-1.0", "100.0")), \
             patch.object(_pb, "close_order") as mock_close, \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", "XAUUSD", DEFAULT_SETTINGS)
            mock_close.assert_not_called()
            mock_chase.assert_not_called()
