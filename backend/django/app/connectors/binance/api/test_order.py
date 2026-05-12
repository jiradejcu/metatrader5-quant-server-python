"""
Tests for chase_order — specifically the modify_order path (when open orders exist).
"""
import os
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call
import pytest

# ---------------------------------------------------------------------------
# Stub out the binance SDK before importing order.py so no real HTTP client
# is constructed at module load time.
# ---------------------------------------------------------------------------

_SDK_PKG = "binance_sdk_derivatives_trading_usds_futures"
_REST_PKG = f"{_SDK_PKG}.derivatives_trading_usds_futures"
_MODELS_PKG = f"{_SDK_PKG}.rest_api.models"

# Top-level package
sdk_top = types.ModuleType(_SDK_PKG)
sys.modules[_SDK_PKG] = sdk_top

# derivatives_trading_usds_futures module
sdk_mod = types.ModuleType(_REST_PKG)
sdk_mod.DerivativesTradingUsdsFutures = MagicMock()
sdk_mod.ConfigurationRestAPI = MagicMock()
sdk_mod.DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL = "https://fapi.binance.com"
sys.modules[_REST_PKG] = sdk_mod

# models module — use real-looking enum-style classes
class _FakeEnum:
    def __init__(self, mapping):
        self._m = mapping
    def __getitem__(self, key):
        return SimpleNamespace(value=self._m[key])

models_mod = types.ModuleType(_MODELS_PKG)
models_mod.NewOrderSideEnum = _FakeEnum({"BUY": "BUY", "SELL": "SELL"})
models_mod.NewOrderTimeInForceEnum = _FakeEnum({"GTX": "GTX"})
models_mod.ModifyOrderSideEnum = _FakeEnum({"BUY": "BUY", "SELL": "SELL"})
models_mod.ModifyOrderPriceMatchEnum = _FakeEnum({"QUEUE": "QUEUE"})
models_mod.ModifyOrderResponse = MagicMock()
sys.modules[_MODELS_PKG] = models_mod

# Stub binance_common.utils.send_request used by _modify_order_with_price_match
_common_pkg = "binance_common"
_common_utils_pkg = "binance_common.utils"
common_mod = types.ModuleType(_common_pkg)
common_utils_mod = types.ModuleType(_common_utils_pkg)
common_utils_mod.send_request = MagicMock()
sys.modules.setdefault(_common_pkg, common_mod)
sys.modules[_common_utils_pkg] = common_utils_mod

# Provide dotenv stub
dotenv_mod = types.ModuleType("dotenv")
dotenv_mod.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_mod)

# Now import the module under test via file path so it works without Django on sys.path
import importlib.util, pathlib

_order_path = pathlib.Path(__file__).parent / "order.py"
_spec = importlib.util.spec_from_file_location("_order_test_mod", str(_order_path))
order = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(order)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_open_order(order_id=12345):
    return SimpleNamespace(order_id=order_id)

def _make_response(data):
    r = MagicMock()
    r.data.return_value = data
    return r


# ---------------------------------------------------------------------------
# Tests for chase_order — modify path
# ---------------------------------------------------------------------------

class TestChaseOrderModify:
    """chase_order when get_open_orders returns at least one order."""

    def _run(self, side="BUY", symbol="BTCUSDT", quantity=0.01, order_id=99):
        open_order = _make_open_order(order_id)
        mock_response = _make_response({"orderId": order_id, "status": "NEW"})

        with patch.object(order, "get_open_orders", return_value=[open_order]), \
             patch.object(order, "_modify_order_with_price_match", return_value=mock_response) as mock_modify:

            result = order.chase_order(symbol, quantity, side)

        return result, mock_modify

    def test_calls_modify_not_new_order(self):
        _, mock_modify = self._run()
        mock_modify.assert_called_once()

    def test_price_match_is_queue(self):
        _, mock_modify = self._run()
        _, kwargs = mock_modify.call_args
        assert kwargs["price_match"] == "QUEUE"

    def test_correct_symbol_quantity_order_id(self):
        _, mock_modify = self._run(symbol="ETHUSDT", quantity=1.5, order_id=777)
        _, kwargs = mock_modify.call_args
        assert kwargs["symbol"] == "ETHUSDT"
        assert kwargs["quantity"] == 1.5
        assert kwargs["order_id"] == 777

    def test_side_buy(self):
        _, mock_modify = self._run(side="BUY")
        _, kwargs = mock_modify.call_args
        assert kwargs["side"] == "BUY"

    def test_side_sell(self):
        _, mock_modify = self._run(side="SELL")
        _, kwargs = mock_modify.call_args
        assert kwargs["side"] == "SELL"

    def test_returns_response_data(self):
        result, _ = self._run(order_id=42)
        assert result == {"orderId": 42, "status": "NEW"}

    def test_returns_none_on_exception(self):
        open_order = _make_open_order(1)
        with patch.object(order, "get_open_orders", return_value=[open_order]), \
             patch.object(order, "_modify_order_with_price_match", side_effect=Exception("API error")):
            result = order.chase_order("BTCUSDT", 0.01, "BUY")
        assert result is None


# ---------------------------------------------------------------------------
# Tests for chase_order — new order path (no open orders)
# ---------------------------------------------------------------------------

class TestChaseOrderNewOrder:
    """chase_order when get_open_orders returns empty list."""

    def _run(self, side="BUY"):
        mock_response = _make_response({"orderId": 1, "status": "NEW"})
        with patch.object(order, "get_open_orders", return_value=[]), \
             patch.object(order.client.rest_api, "new_order", return_value=mock_response) as mock_new, \
             patch.object(order.client.rest_api, "modify_order") as mock_modify:
            result = order.chase_order("BTCUSDT", 0.01, side)
        return result, mock_new, mock_modify

    def test_calls_new_order_not_modify(self):
        _, mock_new, mock_modify = self._run()
        mock_new.assert_called_once()
        mock_modify.assert_not_called()

    def test_returns_response_data(self):
        result, _, _ = self._run()
        assert result == {"orderId": 1, "status": "NEW"}
