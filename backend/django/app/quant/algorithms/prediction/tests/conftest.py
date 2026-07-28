"""
Stub external dependencies so prediction_bot can be loaded in isolation.
These entries must be in sys.modules BEFORE prediction_bot.py is exec'd.

Same rationale as algorithms/arbitrage/tests/conftest.py: intermediate
packages must be plain types.ModuleType (not MagicMock) so `import X.Y.Z`
falls back to sys.modules instead of building a MagicMock attribute chain.
"""
import pathlib
import sys
import types
from unittest.mock import MagicMock

for _name in ("app.connectors", "app.connectors.binance"):
    if _name not in sys.modules:
        _mod = types.ModuleType(_name)
        _mod.__package__ = _name
        sys.modules[_name] = _mod

_api_dir = str(pathlib.Path(__file__).parents[5] / "connectors" / "binance" / "api")
if "app.connectors.binance.api" not in sys.modules:
    _api_mod = types.ModuleType("app.connectors.binance.api")
    _api_mod.__path__ = [_api_dir]
    _api_mod.__package__ = "app.connectors.binance.api"
    sys.modules["app.connectors.binance.api"] = _api_mod

for _name in [
    "app.utils.redis_client",
    "app.connectors.binance.api.order",
    "app.connectors.binance.api.position",
    "app.connectors.binance.api.ticker",
    "app.connectors.binance.api.depth",
]:
    sys.modules.setdefault(_name, MagicMock())
