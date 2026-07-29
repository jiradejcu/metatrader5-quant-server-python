"""
Automated tests for the shared trading_sessions module (used by both
grid_bot and prediction_bot to stay interlocked off one source of truth).

get_redis_connection is patched on the loaded module object; datetime.now
is patched via freezegun-style manual injection isn't needed here since
each test passes an explicit `now` where relevant.
"""
import importlib.util
import json
import pathlib
import sys
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Load trading_sessions.py in isolation: it only does an absolute import of
# app.utils.redis_client, so stub that in sys.modules before exec'ing it —
# no synthetic parent package needed since it has no relative imports.
# ---------------------------------------------------------------------------

sys.modules.setdefault("app.utils.redis_client", MagicMock())

_ts_path = pathlib.Path(__file__).parent.parent / "trading_sessions.py"
_spec = importlib.util.spec_from_file_location("_ts_test_mod", str(_ts_path))
_ts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ts)


# ---------------------------------------------------------------------------
# is_within_trading_session
# ---------------------------------------------------------------------------

class TestIsWithinTradingSession:
    def test_no_config_means_unrestricted(self):
        redis_mock = MagicMock()
        redis_mock.get.return_value = None
        with patch.object(_ts, "get_redis_connection", return_value=redis_mock):
            assert _ts.is_within_trading_session("BTCUSDT", "XAUUSD") is True

    def test_within_configured_range(self):
        sessions = {"Monday": [{"start": "08:00", "end": "16:00"}]}
        redis_mock = MagicMock()
        redis_mock.get.return_value = json.dumps(sessions)
        fixed_now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)  # Monday
        with patch.object(_ts, "get_redis_connection", return_value=redis_mock), \
             patch.object(_ts, "datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_now
            assert _ts.is_within_trading_session("BTCUSDT", "XAUUSD") is True

    def test_outside_configured_range(self):
        sessions = {"Monday": [{"start": "08:00", "end": "16:00"}]}
        redis_mock = MagicMock()
        redis_mock.get.return_value = json.dumps(sessions)
        fixed_now = datetime(2024, 1, 1, 20, 0, tzinfo=timezone.utc)  # Monday
        with patch.object(_ts, "get_redis_connection", return_value=redis_mock), \
             patch.object(_ts, "datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_now
            assert _ts.is_within_trading_session("BTCUSDT", "XAUUSD") is False

    def test_redis_error_defaults_to_unrestricted(self):
        with patch.object(_ts, "get_redis_connection", side_effect=Exception("boom")):
            assert _ts.is_within_trading_session("BTCUSDT", "XAUUSD") is True


# ---------------------------------------------------------------------------
# minutes_until_next_session
# ---------------------------------------------------------------------------

class TestMinutesUntilNextSession:
    def test_no_config_returns_none(self):
        redis_mock = MagicMock()
        redis_mock.get.return_value = None
        with patch.object(_ts, "get_redis_connection", return_value=redis_mock):
            assert _ts.minutes_until_next_session("BTCUSDT", "XAUUSD") is None

    def test_later_range_same_day(self):
        sessions = {"Monday": [{"start": "20:00", "end": "22:00"}]}
        redis_mock = MagicMock()
        redis_mock.get.return_value = json.dumps(sessions)
        fixed_now = datetime(2024, 1, 1, 18, 30, tzinfo=timezone.utc)  # Monday
        with patch.object(_ts, "get_redis_connection", return_value=redis_mock), \
             patch.object(_ts, "datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_now
            assert _ts.minutes_until_next_session("BTCUSDT", "XAUUSD") == pytest.approx(90.0)

    def test_ignores_ranges_already_started_today(self):
        # An earlier-today range that already started must not count as "next".
        sessions = {"Monday": [{"start": "08:00", "end": "16:00"}], "Tuesday": [{"start": "08:00", "end": "16:00"}]}
        redis_mock = MagicMock()
        redis_mock.get.return_value = json.dumps(sessions)
        fixed_now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)  # Monday, mid-session
        with patch.object(_ts, "get_redis_connection", return_value=redis_mock), \
             patch.object(_ts, "datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_now
            # Nothing left today (08:00 already passed) → next is Tuesday 08:00.
            minutes = _ts.minutes_until_next_session("BTCUSDT", "XAUUSD")
            expected = (24 * 60 - 12 * 60) + 8 * 60  # rest of Monday + to 08:00 Tuesday
            assert minutes == pytest.approx(expected)

    def test_rolls_over_to_next_day(self):
        sessions = {"Tuesday": [{"start": "08:00", "end": "16:00"}]}
        redis_mock = MagicMock()
        redis_mock.get.return_value = json.dumps(sessions)
        fixed_now = datetime(2024, 1, 1, 20, 0, tzinfo=timezone.utc)  # Monday night
        with patch.object(_ts, "get_redis_connection", return_value=redis_mock), \
             patch.object(_ts, "datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_now
            # 4h to midnight + 8h to 08:00 Tuesday = 12h = 720 minutes.
            assert _ts.minutes_until_next_session("BTCUSDT", "XAUUSD") == pytest.approx(720.0)

    def test_rolls_over_a_full_week(self):
        # Only Sunday has a session configured; asking on Monday must wrap
        # all the way around to next Sunday, not return None.
        sessions = {"Sunday": [{"start": "08:00", "end": "16:00"}]}
        redis_mock = MagicMock()
        redis_mock.get.return_value = json.dumps(sessions)
        fixed_now = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)  # Monday 2024-01-01
        with patch.object(_ts, "get_redis_connection", return_value=redis_mock), \
             patch.object(_ts, "datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_now
            # Next Sunday is 6 days away, at 08:00.
            expected = 6 * 1440 + 8 * 60
            assert _ts.minutes_until_next_session("BTCUSDT", "XAUUSD") == pytest.approx(expected)

    def test_redis_error_returns_none(self):
        with patch.object(_ts, "get_redis_connection", side_effect=Exception("boom")):
            assert _ts.minutes_until_next_session("BTCUSDT", "XAUUSD") is None
