"""
Stub external dependencies so grid_bot can be loaded in isolation.
These entries must be in sys.modules BEFORE grid_bot.py is exec'd.

Why types.ModuleType for intermediate packages (connectors, binance, api):
  Python's `import X.Y.Z as name` bytecode uses IMPORT_FROM which calls
  getattr(parent, child). MagicMock auto-creates attributes, so the
  sys.modules fallback inside IMPORT_FROM is never triggered and we end up
  with a MagicMock chain instead of the real sub-module.  A plain
  types.ModuleType raises AttributeError on unknown attributes, which
  forces IMPORT_FROM to fall back to sys.modules — where we control exactly
  what each dotted name resolves to.
"""
import pathlib
import sys
import types
from unittest.mock import MagicMock

# --- app.connectors.* intermediate packages ---
# Must be types.ModuleType (not MagicMock) so IMPORT_FROM falls back to
# sys.modules rather than creating child MagicMock chains.
for _name in ("app.connectors", "app.connectors.binance"):
    if _name not in sys.modules:
        _mod = types.ModuleType(_name)
        _mod.__package__ = _name
        sys.modules[_name] = _mod

# app.connectors.binance.api needs __path__ so Python can find real
# submodules (e.g. user_data_stream) on the filesystem.
_api_dir = str(pathlib.Path(__file__).parents[4] / "connectors" / "binance" / "api")
if "app.connectors.binance.api" not in sys.modules:
    _api_mod = types.ModuleType("app.connectors.binance.api")
    _api_mod.__path__ = [_api_dir]
    _api_mod.__package__ = "app.connectors.binance.api"
    sys.modules["app.connectors.binance.api"] = _api_mod

# --- leaf-level stubs: MagicMock is fine here ---
for _name in [
    "app.utils.redis_client",
    "app.connectors.binance.api.order",
    "app.connectors.binance.api.ticker",
    "app.connectors.binance.api.position",
]:
    sys.modules.setdefault(_name, MagicMock())
