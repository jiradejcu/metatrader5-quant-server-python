"""Unit tests for /health and /account_info (MetaTrader5 is stubbed)."""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

# MetaTrader5 only exists inside the Wine container; reuse another test's stub if present.
sys.modules.setdefault("MetaTrader5", types.ModuleType("MetaTrader5"))

from flask import Flask  # noqa: E402

import state  # noqa: E402
from routes import health  # noqa: E402


class _Info:
    def __init__(self, **kw):
        self._kw = kw

    def _asdict(self):
        return dict(self._kw)


ACCOUNT = dict(
    login=123, server="Demo", name="Test", trade_allowed=True, trade_expert=True,
    trade_mode=0, margin_level=0.0, margin_so_call=50.0, margin_so_so=30.0,
    equity=1000.0, balance=1000.0, credit=0.0,
    margin_mode=2, currency="USD", leverage=100,
)


@pytest.fixture
def fake_mt5(monkeypatch):
    fake = types.SimpleNamespace(
        terminal_info=lambda: _Info(trade_allowed=True),
        account_info=lambda: _Info(**ACCOUNT),
    )
    monkeypatch.setattr(health, "mt5", fake)
    return fake


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(health.health_bp)
    return app.test_client()


def test_health_ok_when_connected_and_poll_fresh(fake_mt5, client, monkeypatch):
    monkeypatch.setattr(state, "poll_age", lambda: 1.5)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json() == {
        "status": "healthy", "mt5_connected": True, "mt5_initialized": True, "poll_age_sec": 1.5,
    }


def test_health_503_when_poll_stale(fake_mt5, client, monkeypatch):
    monkeypatch.setattr(state, "poll_age", lambda: state.WATCHDOG_TIMEOUT + 1)
    r = client.get("/health")
    assert r.status_code == 503
    body = r.get_json()
    assert body["status"] == "unhealthy"
    assert body["mt5_connected"] is True
    assert body["poll_age_sec"] == state.WATCHDOG_TIMEOUT + 1


def test_health_ok_at_exact_watchdog_timeout(fake_mt5, client, monkeypatch):
    monkeypatch.setattr(state, "poll_age", lambda: state.WATCHDOG_TIMEOUT)
    assert client.get("/health").status_code == 200


def test_health_503_when_terminal_disconnected(fake_mt5, client, monkeypatch):
    monkeypatch.setattr(state, "poll_age", lambda: 0.2)
    fake_mt5.terminal_info = lambda: None
    r = client.get("/health")
    assert r.status_code == 503
    assert r.get_json()["mt5_connected"] is False


def test_account_info_reports_margin_mode_currency_leverage(fake_mt5, client):
    r = client.get("/account_info")
    assert r.status_code == 200
    body = r.get_json()
    assert body["margin_mode"] == 2
    assert body["currency"] == "USD"
    assert body["leverage"] == 100
    assert body["login"] == 123
