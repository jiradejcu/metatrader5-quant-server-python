"""Unit tests for lib.validate_order market-condition gates (MetaTrader5 is stubbed)."""
import os
import sys
import time
import types
from collections import namedtuple
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

# --- minimal MetaTrader5 stub (module only exists inside the Wine container) ---
mt5 = types.ModuleType("MetaTrader5")
for _name, _val in dict(
    ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1, TRADE_ACTION_DEAL=1, ORDER_TIME_GTC=0,
    ORDER_FILLING_IOC=1, TRADE_RETCODE_DONE=10009, SYMBOL_TRADE_MODE_DISABLED=0,
    BOOK_TYPE_SELL=1, BOOK_TYPE_BUY=2, BOOK_TYPE_SELL_MARKET=3, BOOK_TYPE_BUY_MARKET=4,
    TIMEZONE=None,
).items():
    setattr(mt5, _name, _val)
for _i, _tf in enumerate(['TIMEFRAME_D1', 'TIMEFRAME_H1', 'TIMEFRAME_H4', 'TIMEFRAME_M1', 'TIMEFRAME_M15', 'TIMEFRAME_M30', 'TIMEFRAME_M5', 'TIMEFRAME_MN1', 'TIMEFRAME_W1']):
    setattr(mt5, _tf, _i + 1)  # only needed so constants.py imports
# Real MT5 retcode values so constants.py/lib.py map them exactly like production.
for _n, _c in {'TRADE_RETCODE_REQUOTE': '10004', 'TRADE_RETCODE_REJECT': '10006', 'TRADE_RETCODE_CANCEL': '10007', 'TRADE_RETCODE_PLACED': '10008', 'TRADE_RETCODE_DONE': '10009', 'TRADE_RETCODE_DONE_PARTIAL': '10010', 'TRADE_RETCODE_ERROR': '10011', 'TRADE_RETCODE_TIMEOUT': '10012', 'TRADE_RETCODE_INVALID': '10013', 'TRADE_RETCODE_INVALID_VOLUME': '10014', 'TRADE_RETCODE_INVALID_PRICE': '10015', 'TRADE_RETCODE_INVALID_STOPS': '10016', 'TRADE_RETCODE_TRADE_DISABLED': '10017', 'TRADE_RETCODE_MARKET_CLOSED': '10018', 'TRADE_RETCODE_NO_MONEY': '10019', 'TRADE_RETCODE_PRICE_CHANGED': '10020', 'TRADE_RETCODE_PRICE_OFF': '10021', 'TRADE_RETCODE_INVALID_EXPIRATION': '10022', 'TRADE_RETCODE_ORDER_CHANGED': '10023', 'TRADE_RETCODE_TOO_MANY_REQUESTS': '10024', 'TRADE_RETCODE_NO_CHANGES': '10025', 'TRADE_RETCODE_SERVER_DISABLES_AT': '10026', 'TRADE_RETCODE_CLIENT_DISABLES_AT': '10027', 'TRADE_RETCODE_LOCKED': '10028', 'TRADE_RETCODE_FROZEN': '10029', 'TRADE_RETCODE_INVALID_FILL': '10030', 'TRADE_RETCODE_CONNECTION': '10031', 'TRADE_RETCODE_ONLY_REAL': '10032', 'TRADE_RETCODE_LIMIT_ORDERS': '10033', 'TRADE_RETCODE_LIMIT_VOLUME': '10034', 'TRADE_RETCODE_INVALID_ORDER': '10035', 'TRADE_RETCODE_POSITION_CLOSED': '10036', 'TRADE_RETCODE_INVALID_CLOSE_VOLUME': '10038', 'TRADE_RETCODE_CLOSE_ORDER_EXIST': '10039', 'TRADE_RETCODE_LIMIT_POSITIONS': '10040', 'TRADE_RETCODE_REJECT_CANCEL': '10041', 'TRADE_RETCODE_LONG_ONLY': '10042', 'TRADE_RETCODE_SHORT_ONLY': '10043', 'TRADE_RETCODE_CLOSE_ONLY': '10044', 'TRADE_RETCODE_FIFO_CLOSE': '10045', 'TRADE_RETCODE_HEDGE_PROHIBITED': '10046'}.items():
    setattr(mt5, _n, int(_c))
sys.modules["MetaTrader5"] = mt5

import lib  # noqa: E402

Tick = namedtuple("Tick", "time time_msc bid ask")
Book = namedtuple("Book", "type time price volume time_msc flags volume_dbl")
Check = namedtuple("Check", "retcode balance equity profit margin margin_free margin_level comment request")
SymInfo = types.SimpleNamespace


class _Check:
    """order_check() result with _asdict()."""
    def __init__(self, retcode=0):
        self._d = dict(retcode=retcode, balance=1.0, equity=1.0, profit=0.0, margin=8.57,
                       margin_free=100.0, margin_level=1.0, comment="Done", request=None)

    def _asdict(self):
        return dict(self._d)


@pytest.fixture(autouse=True)
def stub(monkeypatch):
    for k in ("MT5_MAX_TICK_AGE_S", "MT5_SERVER_UTC_OFFSET_H", "MT5_MAX_SPREAD_POINTS",
              "MT5_CHECK_ORDER_BOOK", "MT5_ORDER_BOOK_WAIT_S"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MT5_ORDER_BOOK_WAIT_S", "0")

    now = time.time()
    mt5.symbol_info = MagicMock(return_value=SymInfo(
        visible=True, point=0.001, spread=50, trade_mode=4, volume_min=0.01,
        volume_max=100.0, volume_step=0.01, trade_stops_level=0))
    mt5.symbol_select = MagicMock(return_value=True)
    mt5.symbol_info_tick = MagicMock(return_value=Tick(int(now), int(now * 1000), 4286.002, 4286.052))
    mt5.order_check = MagicMock(return_value=_Check(0))
    mt5.terminal_info = MagicMock(return_value=SimpleNs(connected=True, trade_allowed=True))
    mt5.account_info = MagicMock(return_value=SimpleNs(trade_allowed=True, trade_expert=True))
    mt5.market_book_add = MagicMock(return_value=True)
    mt5.market_book_get = MagicMock(return_value=None)
    mt5.market_book_release = MagicMock(return_value=True)
    mt5.last_error = MagicMock(return_value=(1, "Success"))


def SimpleNs(**kw):
    return types.SimpleNamespace(**kw)


def _check(result, name):
    return next(c for c in result["checks"] if c["name"] == name)


def test_healthy_market_passes_and_reports_market_info():
    r = lib.validate_order("XAUUSD", "SELL", 0.01)
    assert r["ok"] is True
    assert r["failed_checks"] == []
    assert r["market"]["spread_points"] == 50
    assert r["market"]["order_book"]["available"] is False  # no depth from broker → skipped, not failed
    assert _check(r, "order_book_liquidity")["enforced"] is False


def test_stale_tick_means_market_closed():
    old = time.time() - 45000
    mt5.symbol_info_tick.return_value = Tick(int(old), int(old * 1000), 4286.002, 4286.052)
    r = lib.validate_order("XAUUSD", "SELL", 0.01)
    assert r["ok"] is False
    assert r["failed_checks"] == ["tick_fresh"]
    assert "market closed" in r["comment"]


def test_tick_age_check_can_be_disabled(monkeypatch):
    monkeypatch.setenv("MT5_MAX_TICK_AGE_S", "0")
    old = time.time() - 45000
    mt5.symbol_info_tick.return_value = Tick(int(old), int(old * 1000), 4286.002, 4286.052)
    assert lib.validate_order("XAUUSD", "SELL", 0.01)["ok"] is True


def test_server_utc_offset_is_applied(monkeypatch):
    # Server is UTC-5: a live tick is stamped 5h behind UTC.
    behind = time.time() - 5 * 3600
    mt5.symbol_info_tick.return_value = Tick(int(behind), int(behind * 1000), 4286.002, 4286.052)
    assert lib.validate_order("XAUUSD", "SELL", 0.01)["failed_checks"] == ["tick_fresh"]  # offset unset → looks stale
    monkeypatch.setenv("MT5_SERVER_UTC_OFFSET_H", "-5")
    r = lib.validate_order("XAUUSD", "SELL", 0.01)
    assert r["ok"] is True and r["market"]["tick_age_s"] < 5


def test_spread_gate_only_enforced_when_limit_set(monkeypatch):
    assert _check(lib.validate_order("XAUUSD", "BUY", 0.01), "spread_ok")["enforced"] is False
    monkeypatch.setenv("MT5_MAX_SPREAD_POINTS", "30")
    r = lib.validate_order("XAUUSD", "BUY", 0.01)
    assert r["ok"] is False and r["failed_checks"] == ["spread_ok"]
    monkeypatch.setenv("MT5_MAX_SPREAD_POINTS", "100")
    assert lib.validate_order("XAUUSD", "BUY", 0.01)["ok"] is True


def test_order_book_thin_side_rejects_sell():
    # SELL hits bids: 0.005 lots at best bid, far levels outside 20-point deviation.
    now = int(time.time())
    mt5.market_book_get.return_value = [
        Book(2, now, 4286.002, 0, 0, 0, 0.005),   # bid within deviation
        Book(2, now, 4280.000, 0, 0, 0, 5.0),     # bid far away (outside 20 pts)
        Book(1, now, 4286.052, 0, 0, 0, 50.0),    # ask side — must be ignored for SELL
    ]
    r = lib.validate_order("XAUUSD", "SELL", 0.01)
    book = r["market"]["order_book"]
    assert book["available"] is True and book["side"] == "bid"
    assert book["volume_within_deviation"] == pytest.approx(0.005)
    assert r["ok"] is False and r["failed_checks"] == ["order_book_liquidity"]
    mt5.market_book_release.assert_called_once_with("XAUUSD")


def test_order_book_enough_liquidity_passes_buy_and_reports_vwap():
    now = int(time.time())
    mt5.market_book_get.return_value = [
        Book(1, now, 4286.052, 0, 0, 0, 0.006),
        Book(1, now, 4286.060, 0, 0, 0, 0.010),
        Book(2, now, 4286.002, 0, 0, 0, 0.001),   # bid side ignored for BUY
    ]
    r = lib.validate_order("XAUUSD", "BUY", 0.01)
    book = r["market"]["order_book"]
    assert r["ok"] is True
    assert book["side"] == "ask" and book["fillable_volume"] == pytest.approx(0.01)
    assert 4286.052 < book["vwap"] < 4286.060


def test_book_without_volume_or_disabled_is_skipped(monkeypatch):
    now = int(time.time())
    mt5.market_book_get.return_value = [Book(2, now, 4286.0, 0, 0, 0, 0.0)]
    assert lib.validate_order("XAUUSD", "SELL", 0.01)["ok"] is True
    monkeypatch.setenv("MT5_CHECK_ORDER_BOOK", "false")
    mt5.market_book_add.reset_mock()
    assert lib.validate_order("XAUUSD", "SELL", 0.01)["ok"] is True
    mt5.market_book_add.assert_not_called()


def test_algo_trading_disabled_rejects():
    mt5.terminal_info.return_value = SimpleNs(connected=True, trade_allowed=False)
    r = lib.validate_order("XAUUSD", "SELL", 0.01)
    assert r["ok"] is False and "algo_trading_enabled" in r["failed_checks"]


def test_order_check_failure_keeps_broker_reason_and_appends_gate_failures():
    mt5.order_check.return_value = _Check(10014)
    old = time.time() - 45000
    mt5.symbol_info_tick.return_value = Tick(int(old), int(old * 1000), 4286.002, 4286.052)
    r = lib.validate_order("XAUUSD", "BUY", 1000)
    assert r["ok"] is False and r["retcode"] == 10014
    assert r["comment"].startswith("Invalid volume")
    assert "market closed" in r["comment"]


def test_retcode_zero_is_success():
    assert lib.validate_order("XAUUSD", "BUY", 0.01)["ok"] is True
