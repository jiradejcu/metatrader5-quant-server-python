"""
Stub external dependencies so grid_bot can be loaded in isolation.
These entries must be in sys.modules BEFORE grid_bot.py is exec'd.
"""
import sys
from unittest.mock import MagicMock

for _mod in [
    "app.utils.redis_client",
    "app.connectors",
    "app.connectors.binance",
    "app.connectors.binance.api",
    "app.connectors.binance.api.order",
    "app.connectors.binance.api.ticker",
    "app.connectors.binance.api.position",
]:
    sys.modules.setdefault(_mod, MagicMock())
