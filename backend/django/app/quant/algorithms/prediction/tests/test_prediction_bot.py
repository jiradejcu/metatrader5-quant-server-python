"""
Automated tests for prediction_bot trading logic.

External Binance calls (get_position, get_ticker, get_open_orders,
cancel_all_open_orders, chase_order, get_order_book, close_order) are
patched on the loaded module object.
"""
import importlib.util
import pathlib
import queue
import sys
import types
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

# --- trading_sessions: load the real module (shared with grid_bot) ---
_ts_path = pathlib.Path(__file__).parents[2] / "trading_sessions.py"
_ts_spec = importlib.util.spec_from_file_location(f"{_PKG}.trading_sessions", str(_ts_path))
_ts_mod = importlib.util.module_from_spec(_ts_spec)
sys.modules[f"{_PKG}.trading_sessions"] = _ts_mod
_ts_spec.loader.exec_module(_ts_mod)

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

def _position(position_amt="0", entry_price="0"):
    return {"positionAmt": position_amt, "entryPrice": entry_price}


def _open_order(side="SELL", orig_qty=1.0, order_id=123):
    return SimpleNamespace(side=side, orig_qty=orig_qty, order_id=order_id)


DEFAULT_SETTINGS = {
    "profit_target_usd": 5.0,
    "max_slippage_usd": 2.0,
    "aggressiveness": "passive",
    "reentry_tolerance_usd": 0.0,
    "max_close_size": 0.0,
}

AGGRESSIVE_SETTINGS = dict(DEFAULT_SETTINGS, aggressiveness="aggressive")


@pytest.fixture(autouse=True)
def reset_globals():
    _pb.latest_prediction_settings = None
    _pb._last_position = {"entry_price": None, "qty": None}
    _pb._original_position_qty = {"value": None}
    yield
    _pb.latest_prediction_settings = None
    _pb._last_position = {"entry_price": None, "qty": None}
    _pb._original_position_qty = {"value": None}


# ---------------------------------------------------------------------------
# _parse_prediction_settings
# ---------------------------------------------------------------------------

class TestParsePredictionSettings:
    def test_parses_all_fields(self):
        raw = {
            "profit_target_usd": "3",
            "max_slippage_usd": "1.5",
            "aggressiveness": "aggressive",
            "reentry_tolerance_usd": "0.5",
            "max_close_size": "0.25",
        }
        parsed = _pb._parse_prediction_settings(raw)
        assert parsed == {
            "profit_target_usd": 3.0,
            "max_slippage_usd": 1.5,
            "aggressiveness": "aggressive",
            "reentry_tolerance_usd": 0.5,
            "max_close_size": 0.25,
        }

    def test_defaults_missing_fields(self):
        assert _pb._parse_prediction_settings({}) == {
            "profit_target_usd": 0.0,
            "max_slippage_usd": 0.0,
            "aggressiveness": "passive",
            "reentry_tolerance_usd": 0.0,
            "max_close_size": 0.0,
        }

    def test_normalizes_case_and_whitespace(self):
        parsed = _pb._parse_prediction_settings({"aggressiveness": " Aggressive "})
        assert parsed["aggressiveness"] == "aggressive"

    def test_falls_back_to_passive_on_unrecognized_value(self):
        parsed = _pb._parse_prediction_settings({"aggressiveness": "yolo"})
        assert parsed["aggressiveness"] == "passive"


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
# _capped_close_qty
# ---------------------------------------------------------------------------

class TestCappedCloseQty:
    def test_uncapped_when_zero(self):
        assert _pb._capped_close_qty(5.0, 0.0) == 5.0

    def test_uncapped_when_negative(self):
        assert _pb._capped_close_qty(5.0, -1.0) == 5.0

    def test_caps_to_max_close_size(self):
        assert _pb._capped_close_qty(5.0, 2.0) == 2.0

    def test_does_not_exceed_position_when_cap_is_larger(self):
        assert _pb._capped_close_qty(5.0, 10.0) == 5.0


# ---------------------------------------------------------------------------
# _process_tick state machine
# ---------------------------------------------------------------------------

class TestProcessTickIdle:
    def test_does_nothing_without_position_or_orders(self):
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker") as mock_ticker, \
             patch.object(_pb, "chase_order") as mock_chase, \
             patch.object(_pb, "cancel_all_open_orders") as mock_cancel:
            _pb._process_tick("BTCUSDT", DEFAULT_SETTINGS)
            mock_ticker.assert_not_called()
            mock_chase.assert_not_called()
            mock_cancel.assert_not_called()

    def test_cancels_stray_order_without_a_position(self):
        order = _open_order()
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[order]), \
             patch.object(_pb, "cancel_all_open_orders") as mock_cancel:
            _pb._process_tick("BTCUSDT", DEFAULT_SETTINGS)
            mock_cancel.assert_called_once_with("BTCUSDT")


class TestProcessTickHolding:
    """position_amt > 0, no close order resting yet (passive mode)."""

    def test_holds_when_profit_below_target(self):
        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 103.0, "best_ask": 103.5}), \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", DEFAULT_SETTINGS)  # target=5.0
            mock_chase.assert_not_called()

    def test_places_close_order_when_profit_target_hit(self):
        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 106.0, "best_ask": 106.5}), \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", DEFAULT_SETTINGS)  # profit=6 >= target=5
            mock_chase.assert_called_once_with("BTCUSDT", 1.0, "SELL", order_id=None)

    def test_skips_unexpected_short_position(self):
        with patch.object(_pb, "get_position", return_value=_position("-1.0", "100.0")), \
             patch.object(_pb, "get_open_orders") as mock_open_orders, \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", DEFAULT_SETTINGS)
            mock_open_orders.assert_not_called()
            mock_chase.assert_not_called()


class TestProcessTickClosing:
    """position_amt > 0, a close SELL order is already resting (passive mode)."""

    def test_chases_existing_sell_order_while_target_still_met(self):
        order = _open_order(side="SELL", orig_qty=1.0, order_id=42)
        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_open_orders", return_value=[order]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 106.0, "best_ask": 106.5}), \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", DEFAULT_SETTINGS)  # profit=6 >= target=5
            mock_chase.assert_called_once_with("BTCUSDT", 1.0, "SELL", order_id=42)

    def test_cancels_when_target_no_longer_met(self):
        order = _open_order(side="SELL")
        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_open_orders", return_value=[order]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 103.0, "best_ask": 103.5}), \
             patch.object(_pb, "cancel_all_open_orders") as mock_cancel, \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", DEFAULT_SETTINGS)  # profit=3 < target=5
            mock_cancel.assert_called_once_with("BTCUSDT")
            mock_chase.assert_not_called()

    def test_cancels_unexpected_buy_order_while_closing(self):
        order = _open_order(side="BUY")
        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_open_orders", return_value=[order]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 106.0, "best_ask": 106.5}), \
             patch.object(_pb, "cancel_all_open_orders") as mock_cancel:
            _pb._process_tick("BTCUSDT", DEFAULT_SETTINGS)  # profit=6 >= target=5
            mock_cancel.assert_called_once_with("BTCUSDT")


class TestProcessTickAggressive:
    """position_amt > 0, settings['aggressiveness'] == 'aggressive'."""

    def test_holds_when_profit_below_target(self):
        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 103.0, "best_ask": 103.5}), \
             patch.object(_pb, "close_order") as mock_close:
            _pb._process_tick("BTCUSDT", AGGRESSIVE_SETTINGS)  # target=5.0
            mock_close.assert_not_called()

    def test_closes_when_profit_target_hit_and_depth_sufficient(self):
        order_book = {"bids": [(105.0, 2.0)], "asks": []}
        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 106.0, "best_ask": 106.5}), \
             patch.object(_pb, "get_order_book", return_value=order_book), \
             patch.object(_pb, "close_order") as mock_close:
            _pb._process_tick("BTCUSDT", AGGRESSIVE_SETTINGS)  # profit=6 >= target=5
            mock_close.assert_called_once_with("BTCUSDT", 1.0, "SELL", 105.0)

    def test_waits_when_book_too_thin_for_slippage_budget(self):
        # best bid far from remaining book — any close would blow the slippage budget.
        order_book = {"bids": [(90.0, 0.0001)], "asks": []}
        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 106.0, "best_ask": 106.5}), \
             patch.object(_pb, "get_order_book", return_value=order_book), \
             patch.object(_pb, "close_order") as mock_close:
            _pb._process_tick("BTCUSDT", AGGRESSIVE_SETTINGS)
            mock_close.assert_not_called()

    def test_cancels_resting_passive_order_before_switching_to_aggressive(self):
        # aggressiveness was just flipped mid-flight — a passive chase order
        # from before is still resting. Pull it before crossing the book.
        order = _open_order(side="SELL")
        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_open_orders", return_value=[order]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 106.0, "best_ask": 106.5}), \
             patch.object(_pb, "cancel_all_open_orders") as mock_cancel, \
             patch.object(_pb, "close_order") as mock_close:
            _pb._process_tick("BTCUSDT", AGGRESSIVE_SETTINGS)  # profit=6 >= target=5
            mock_cancel.assert_called_once_with("BTCUSDT")
            mock_close.assert_not_called()


class TestProcessTickReacquire:
    """position_amt == 0, reentry_tolerance_usd > 0 and a prior close is remembered."""

    REENTRY_SETTINGS = dict(DEFAULT_SETTINGS, reentry_tolerance_usd=1.0)

    def test_no_reacquire_without_a_remembered_position(self):
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker") as mock_ticker, \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", self.REENTRY_SETTINGS)
            mock_ticker.assert_not_called()
            mock_chase.assert_not_called()

    def test_no_reacquire_when_tolerance_is_zero(self):
        _pb._last_position['entry_price'] = 100.0
        _pb._last_position['qty'] = 1.0
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker") as mock_ticker, \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", DEFAULT_SETTINGS)  # reentry_tolerance_usd=0.0
            mock_ticker.assert_not_called()
            mock_chase.assert_not_called()

    def test_waits_when_price_still_above_reentry_band(self):
        _pb._last_position['entry_price'] = 100.0
        _pb._last_position['qty'] = 1.0
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 104.5, "best_ask": 105.0}), \
             patch.object(_pb, "chase_order") as mock_chase, \
             patch.object(_pb, "cancel_all_open_orders") as mock_cancel:
            _pb._process_tick("BTCUSDT", self.REENTRY_SETTINGS)  # band = 101.0, ask=105.0
            mock_chase.assert_not_called()
            mock_cancel.assert_not_called()

    def test_places_reacquire_order_when_price_falls_back_to_entry(self):
        _pb._last_position['entry_price'] = 100.0
        _pb._last_position['qty'] = 2.0
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 100.0, "best_ask": 100.5}), \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", self.REENTRY_SETTINGS)  # ask=100.5 <= band=101.0
            mock_chase.assert_called_once_with("BTCUSDT", 2.0, "BUY", order_id=None)

    def test_chases_existing_reacquire_order(self):
        _pb._last_position['entry_price'] = 100.0
        _pb._last_position['qty'] = 2.0
        order = _open_order(side="BUY", orig_qty=2.0, order_id=77)
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[order]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 100.0, "best_ask": 100.5}), \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", self.REENTRY_SETTINGS)
            mock_chase.assert_called_once_with("BTCUSDT", 2.0, "BUY", order_id=77)

    def test_cancels_resting_reacquire_order_when_price_moves_back_up(self):
        _pb._last_position['entry_price'] = 100.0
        _pb._last_position['qty'] = 2.0
        order = _open_order(side="BUY", orig_qty=2.0, order_id=77)
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[order]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 104.5, "best_ask": 105.0}), \
             patch.object(_pb, "cancel_all_open_orders") as mock_cancel, \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", self.REENTRY_SETTINGS)
            mock_cancel.assert_called_once_with("BTCUSDT")
            mock_chase.assert_not_called()

    def test_cancels_unexpected_sell_order_while_reacquiring(self):
        _pb._last_position['entry_price'] = 100.0
        _pb._last_position['qty'] = 2.0
        order = _open_order(side="SELL")
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[order]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 100.0, "best_ask": 100.5}), \
             patch.object(_pb, "cancel_all_open_orders") as mock_cancel:
            _pb._process_tick("BTCUSDT", self.REENTRY_SETTINGS)
            mock_cancel.assert_called_once_with("BTCUSDT")


class TestFullCloseThenReacquireCycle:
    def test_remembers_entry_price_on_close_and_reacquires_on_dip(self):
        settings = dict(DEFAULT_SETTINGS, reentry_tolerance_usd=1.0)

        # Holding, profit target hit → closes and remembers entry/qty.
        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 106.0, "best_ask": 106.5}), \
             patch.object(_pb, "chase_order") as mock_chase_close:
            _pb._process_tick("BTCUSDT", settings)
            mock_chase_close.assert_called_once_with("BTCUSDT", 1.0, "SELL", order_id=None)

        assert _pb._last_position == {"entry_price": 100.0, "qty": 1.0}

        # Flat now, price fell back to entry → reacquires the same size.
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 100.2, "best_ask": 100.5}), \
             patch.object(_pb, "chase_order") as mock_chase_reacquire:
            _pb._process_tick("BTCUSDT", settings)
            mock_chase_reacquire.assert_called_once_with("BTCUSDT", 1.0, "BUY", order_id=None)


class TestMaxCloseSize:
    """settings['max_close_size'] clips each close order's size."""

    def test_passive_close_capped_to_max_close_size(self):
        settings = dict(DEFAULT_SETTINGS, max_close_size=0.4)
        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 106.0, "best_ask": 106.5}), \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", settings)  # profit=6 >= target=5
            mock_chase.assert_called_once_with("BTCUSDT", 0.4, "SELL", order_id=None)

    def test_passive_close_uncapped_when_position_smaller_than_cap(self):
        settings = dict(DEFAULT_SETTINGS, max_close_size=5.0)
        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 106.0, "best_ask": 106.5}), \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", settings)
            mock_chase.assert_called_once_with("BTCUSDT", 1.0, "SELL", order_id=None)

    def test_aggressive_close_capped_to_max_close_size(self):
        settings = dict(AGGRESSIVE_SETTINGS, max_close_size=0.4, max_slippage_usd=10.0)
        order_book = {"bids": [(105.0, 10.0)], "asks": []}
        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 106.0, "best_ask": 106.5}), \
             patch.object(_pb, "get_order_book", return_value=order_book), \
             patch.object(_pb, "close_order") as mock_close:
            _pb._process_tick("BTCUSDT", settings)  # book has plenty of depth, cap should bind
            mock_close.assert_called_once_with("BTCUSDT", 0.4, "SELL", 105.0)

    def test_original_qty_stays_fixed_across_partial_closes_for_reacquire(self):
        # Position starts at 1.0, gets clipped down to 0.6 then 0.2 by
        # max_close_size=0.4 closes over successive ticks, then goes flat.
        # The remembered reacquire size must be the ORIGINAL 1.0, not 0.2.
        settings = dict(DEFAULT_SETTINGS, max_close_size=0.4, reentry_tolerance_usd=1.0)

        with patch.object(_pb, "get_position", return_value=_position("1.0", "100.0")), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 106.0, "best_ask": 106.5}), \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", settings)
            mock_chase.assert_called_once_with("BTCUSDT", 0.4, "SELL", order_id=None)
        assert _pb._last_position == {"entry_price": 100.0, "qty": 1.0}

        with patch.object(_pb, "get_position", return_value=_position("0.6", "100.0")), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 106.0, "best_ask": 106.5}), \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", settings)
            mock_chase.assert_called_once_with("BTCUSDT", 0.4, "SELL", order_id=None)
        assert _pb._last_position == {"entry_price": 100.0, "qty": 1.0}

        with patch.object(_pb, "get_position", return_value=_position("0.2", "100.0")), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 106.0, "best_ask": 106.5}), \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", settings)
            mock_chase.assert_called_once_with("BTCUSDT", 0.2, "SELL", order_id=None)
        assert _pb._last_position == {"entry_price": 100.0, "qty": 1.0}

        # Now flat — reacquire must target the original 1.0, not the last 0.2 clip.
        with patch.object(_pb, "get_position", return_value=_position()), \
             patch.object(_pb, "get_open_orders", return_value=[]), \
             patch.object(_pb, "get_ticker", return_value={"best_bid": 100.2, "best_ask": 100.5}), \
             patch.object(_pb, "chase_order") as mock_chase:
            _pb._process_tick("BTCUSDT", settings)
            mock_chase.assert_called_once_with("BTCUSDT", 1.0, "BUY", order_id=None)


# ---------------------------------------------------------------------------
# _reset_position_tracking
# ---------------------------------------------------------------------------

class TestResetPositionTracking:
    def test_clears_original_qty_and_last_position(self):
        _pb._original_position_qty['value'] = 3.0
        _pb._last_position['entry_price'] = 100.0
        _pb._last_position['qty'] = 3.0

        _pb._reset_position_tracking()

        assert _pb._original_position_qty == {"value": None}
        assert _pb._last_position == {"entry_price": None, "qty": None}


# ---------------------------------------------------------------------------
# handle_prediction_flow — trading-session boundary anchors tracking
# ---------------------------------------------------------------------------

class _StopLoop(BaseException):
    """Sentinel to break handle_prediction_flow's infinite tick loop.

    Must subclass BaseException, not Exception, because the loop has a bare
    `except Exception` that would otherwise swallow this and loop forever.
    """


def _blocking_pubsub():
    """A pubsub whose listen() blocks forever on an empty queue — same idle,
    no-CPU-spin behavior as grid_bot's tests get from Event.wait().
    """
    pubsub = MagicMock()

    def _listen():
        q = queue.Queue()
        while True:
            yield q.get()

    pubsub.listen.side_effect = _listen
    return pubsub


def _run_handle_prediction_flow_for_sessions(session_values):
    """Drive handle_prediction_flow through len(session_values) tick-loop
    iterations, one is_within_trading_session() reading per iteration
    (patched to return them in order), then stop. Returns the
    _reset_position_tracking mock so callers can assert on call count.
    """
    redis_mock = MagicMock()
    redis_mock.get.return_value = None

    sleep_calls = {"count": 0}

    def _fake_sleep(_):
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= len(session_values):
            raise _StopLoop("done")

    session_iter = iter(session_values)

    with patch.object(_pb, "get_redis_connection", return_value=redis_mock), \
         patch.object(_pb, "get_active_status", return_value=True), \
         patch.object(_pb, "is_within_trading_session", side_effect=lambda *a, **k: next(session_iter)), \
         patch.object(_pb, "time") as mock_time, \
         patch.object(_pb, "_reset_position_tracking") as mock_reset, \
         patch.object(_pb, "_process_tick"):
        mock_time.sleep.side_effect = _fake_sleep
        try:
            _pb.handle_prediction_flow(_blocking_pubsub(), "settings_channel", "BTCUSDT", "XAUUSD", poll_interval=0)
        except _StopLoop:
            pass

    return mock_reset


class TestHandleFlowTradingSessionAnchor:
    def test_resets_exactly_once_on_session_close_transition(self):
        mock_reset = _run_handle_prediction_flow_for_sessions([True, False, False, False])
        mock_reset.assert_called_once()

    def test_no_reset_while_continuously_in_session(self):
        mock_reset = _run_handle_prediction_flow_for_sessions([True, True, True])
        mock_reset.assert_not_called()

    def test_resets_immediately_if_first_tick_is_already_out_of_session(self):
        # A freshly (re)started bot assumes it just came from in-session, so
        # discovering it's already out-of-session on tick one still anchors.
        mock_reset = _run_handle_prediction_flow_for_sessions([False])
        mock_reset.assert_called_once()
