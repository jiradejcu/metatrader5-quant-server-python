"""
Tests for position_sync's recovery mode.

When a hedge market order is rejected purely because of market conditions
(thin liquidity, requote, no quotes, ...), position_sync must put the grid
bot into recovery mode instead of disabling it, stop hedging the discrepancy,
and probe the market with minimum-volume orders until one fills. Any failure
with a known cause (outside session, no money, market closed, MT5 down) keeps
the old behaviour: disable the grid bot.
"""
import importlib.util
import json
import pathlib
import sys
import types
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

_PKG = "_ps_test_pkg"

_root = types.ModuleType(_PKG)
_root.__path__ = []
sys.modules[_PKG] = _root

_arbitrage_pkg = types.ModuleType(f"{_PKG}.arbitrage")
_arbitrage_pkg.__path__ = []
sys.modules[f"{_PKG}.arbitrage"] = _arbitrage_pkg

_config_mod = types.ModuleType(f"{_PKG}.arbitrage.config")
_real_config_spec = importlib.util.spec_from_file_location(
    "_ps_real_config", pathlib.Path(__file__).parent.parent / "config.py")
_real_config = importlib.util.module_from_spec(_real_config_spec)
_real_config_spec.loader.exec_module(_real_config)
_config_mod.PAIRS = _real_config.PAIRS
sys.modules[f"{_PKG}.arbitrage.config"] = _config_mod

_ts_mod = types.ModuleType(f"{_PKG}.trading_sessions")
_ts_mod.is_within_trading_session = lambda *a, **k: True
sys.modules[f"{_PKG}.trading_sessions"] = _ts_mod

sys.modules.setdefault("app.utils.position_group", MagicMock())

_ps_path = pathlib.Path(__file__).parent.parent / "position_sync.py"
_spec = importlib.util.spec_from_file_location(f"{_PKG}.arbitrage.position_sync", str(_ps_path))
_ps = importlib.util.module_from_spec(_spec)
_ps.__package__ = f"{_PKG}.arbitrage"
sys.modules[f"{_PKG}.arbitrage.position_sync"] = _ps
_spec.loader.exec_module(_ps)

HEDGE = "XAUUSD"  # PAIR_INDEX=1: XAUUSDT / XAUUSD, contract_size=100, min amount 1
PRIMARY = "XAUUSDT"

REJECT = 10006
NO_MONEY = 10019
MARKET_CLOSED = 10018


class FakeRedis:
    def __init__(self, initial=None):
        self.store = dict(initial or {})

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value if isinstance(value, bytes) else str(value).encode()

    def delete(self, key):
        self.store.pop(key, None)


def _err(retcode, comment="rejected"):
    return {"retcode": retcode, "comment": comment, "http_status": 400}


def _validate(ok=True, retcode=0, failed_checks=()):
    return {"ok": ok, "retcode": retcode, "comment": "dry-run", "failed_checks": list(failed_checks)}


@pytest.fixture(autouse=True)
def env_and_globals():
    _ps.pre_order_volume = None
    _ps._consecutive_errors = 0
    _ps._last_probe_ts = 0.0
    with patch.dict("os.environ", {"PAIR_INDEX": "1", "MOCK_ENTRY_POSITION_AMT": "false"}), \
         patch.object(_ps, "is_within_trading_session", return_value=True), \
         patch.object(_ps, "validate_order", return_value=_validate()) as mock_validate:
        yield mock_validate


# ---------------------------------------------------------------------------
# failure classification
# ---------------------------------------------------------------------------

class TestIsMarketConditionFailure:

    def _classify(self, error):
        return _ps._is_market_condition_failure(error, HEDGE, "SELL", Decimal("0.05"))[0]

    @pytest.mark.parametrize("retcode", sorted(_ps._MARKET_CONDITION_RETCODES))
    def test_market_condition_retcodes(self, retcode):
        assert self._classify(_err(retcode)) is True

    @pytest.mark.parametrize("retcode", [NO_MONEY, MARKET_CLOSED, 10017, 10027, 10031, 10014, None])
    def test_known_or_unknown_causes_are_not_market(self, retcode):
        assert self._classify(_err(retcode)) is False

    def test_transport_error_is_not_market(self):
        assert self._classify({"retcode": None, "comment": "Timeout sending order", "http_status": None}) is False

    def test_outside_trading_session_is_not_market(self):
        with patch.object(_ps, "is_within_trading_session", return_value=False):
            assert self._classify(_err(REJECT)) is False

    def test_dry_run_no_money_overrides_generic_reject(self, env_and_globals):
        env_and_globals.return_value = _validate(ok=False, retcode=NO_MONEY)
        assert self._classify(_err(REJECT)) is False

    @pytest.mark.parametrize("check", sorted(_ps._NON_MARKET_CHECKS))
    def test_dry_run_non_market_check_overrides(self, env_and_globals, check):
        env_and_globals.return_value = _validate(ok=False, failed_checks=[check])
        assert self._classify(_err(REJECT)) is False

    @pytest.mark.parametrize("check", ["order_book_liquidity", "spread_ok"])
    def test_dry_run_liquidity_failure_is_market(self, env_and_globals, check):
        env_and_globals.return_value = _validate(ok=False, failed_checks=[check])
        assert self._classify(_err(REJECT)) is True

    def test_dry_run_unreachable_gives_no_extra_info(self, env_and_globals):
        env_and_globals.return_value = {"ok": False, "comment": "Timeout validating order"}
        assert self._classify(_err(REJECT)) is True

    def test_dry_run_uses_failed_order(self, env_and_globals):
        self._classify(_err(REJECT))
        env_and_globals.assert_called_once_with(symbol=HEDGE, order_type="SELL", volume=0.05)


# ---------------------------------------------------------------------------
# handle_position_update
# ---------------------------------------------------------------------------

def _message(position_amt):
    return {"type": "message", "data": json.dumps({
        "symbol": PRIMARY, "positionAmt": str(position_amt), "entryPrice": "2000", "markPrice": "2000",
    })}


def _run(redis, messages, hedge_volume, send_results):
    """Feed messages through handle_position_update; return the send mock."""
    pubsub = MagicMock()
    pubsub.listen.return_value = iter(messages)
    with patch.object(_ps, "get_redis_connection", return_value=redis), \
         patch.object(_ps, "get_hedge_position", return_value={"volume": str(hedge_volume)}), \
         patch.object(_ps, "resolve_group_id", return_value="g1"), \
         patch.object(_ps, "make_comment", return_value="c"), \
         patch.object(_ps, "update_position_group"), \
         patch.object(_ps, "get_position_group", return_value=None), \
         patch.object(_ps, "send_market_order", side_effect=send_results) as mock_send:
        _ps.handle_position_update(pubsub)
    return mock_send


_FILLED = ({"price": 2000.0, "volume": 0.01}, None)


class TestOrderFailure:

    def test_market_condition_enters_recovery_keeps_grid_enabled(self):
        redis = FakeRedis({"grid_bot_enabled_flag": b"1"})
        _run(redis, [_message(5)], 0, [(None, _err(REJECT))])
        assert redis.get("grid_bot_recovery_flag") is not None
        assert redis.get("grid_bot_enabled_flag") == b"1"
        assert redis.get("position_sync_ok_flag") == b"1"

    def test_known_failure_disables_grid_bot(self):
        redis = FakeRedis({"grid_bot_enabled_flag": b"1"})
        _run(redis, [_message(5)], 0, [(None, _err(NO_MONEY))])
        assert redis.get("grid_bot_recovery_flag") is None
        assert redis.get("grid_bot_enabled_flag") is None

    def test_successful_hedge_does_not_enter_recovery(self):
        redis = FakeRedis({"grid_bot_enabled_flag": b"1"})
        send = _run(redis, [_message(5)], 0, [({"price": 2000.0, "volume": 0.05}, None)])
        send.assert_called_once()
        assert send.call_args.kwargs["order_type"] == "SELL"
        assert send.call_args.kwargs["volume"] == Decimal("0.05")
        assert redis.get("grid_bot_recovery_flag") is None


class TestRecoveryProbe:

    def _recovering(self):
        return FakeRedis({"grid_bot_enabled_flag": b"1", "grid_bot_recovery_flag": b"{}"})

    def test_no_probe_before_interval(self):
        redis = self._recovering()
        _ps._last_probe_ts = _ps.time.monotonic()
        send = _run(redis, [_message(5)], 0, [])
        send.assert_not_called()
        assert redis.get("position_sync_ok_flag") == b"1"

    def test_probe_uses_min_volume_not_full_discrepancy(self):
        redis = self._recovering()
        send = _run(redis, [_message(5)], 0, [_FILLED])
        send.assert_called_once()
        assert send.call_args.kwargs["volume"] == Decimal("0.01")
        assert send.call_args.kwargs["order_type"] == "SELL"  # reduces the discrepancy

    def test_probe_without_discrepancy_shrinks_hedge(self):
        redis = self._recovering()
        send = _run(redis, [_message(3)], -0.03, [_FILLED])
        assert send.call_args.kwargs["order_type"] == "BUY"

    def test_probe_success_exits_recovery(self):
        redis = self._recovering()
        _run(redis, [_message(5)], 0, [_FILLED])
        assert redis.get("grid_bot_recovery_flag") is None
        assert redis.get("sync_pending_flag") == b"1"
        assert _ps.pre_order_volume == Decimal("0")

    def test_probe_market_failure_stays_in_recovery(self):
        redis = self._recovering()
        _run(redis, [_message(5)], 0, [(None, _err(REJECT))])
        assert redis.get("grid_bot_recovery_flag") is not None
        assert redis.get("grid_bot_enabled_flag") == b"1"

    def test_probe_known_failure_disables_grid_and_exits_recovery(self):
        redis = self._recovering()
        _run(redis, [_message(5)], 0, [(None, _err(MARKET_CLOSED))])
        assert redis.get("grid_bot_recovery_flag") is None
        assert redis.get("grid_bot_enabled_flag") is None

    def test_probe_throttled_across_messages(self):
        redis = self._recovering()
        send = _run(redis, [_message(5), _message(5), _message(5)], 0, [(None, _err(REJECT))])
        send.assert_called_once()


# ---------------------------------------------------------------------------
# hedge-safety: never hedge off a position we couldn't read, never hedge twice
# ---------------------------------------------------------------------------

class TestHedgePositionUnavailable:

    def test_skips_pass_without_order_error_or_heartbeat(self):
        redis = FakeRedis({"grid_bot_enabled_flag": b"1"})
        pubsub = MagicMock()
        pubsub.listen.return_value = iter([_message(5)])
        with patch.object(_ps, "get_redis_connection", return_value=redis), \
             patch.object(_ps, "get_hedge_position", side_effect=_ps.PositionsUnavailable("MT5 503")), \
             patch.object(_ps, "send_market_order") as mock_send:
            _ps.handle_position_update(pubsub)
        mock_send.assert_not_called()
        assert _ps._consecutive_errors == 0
        assert redis.get("position_sync_ok_flag") is None
        assert redis.get("grid_bot_enabled_flag") == b"1"


class TestNoDoubleHedgeAfterFill:

    def test_redis_failure_after_fill_still_blocks_second_hedge(self):
        redis = FakeRedis({"grid_bot_enabled_flag": b"1"})
        pubsub = MagicMock()
        # Same (stale) hedge volume on both passes — the fill isn't visible yet.
        pubsub.listen.return_value = iter([_message(5), _message(5)])
        with patch.object(_ps, "get_redis_connection", return_value=redis), \
             patch.object(_ps, "get_hedge_position", return_value={"volume": "0"}), \
             patch.object(_ps, "resolve_group_id", return_value="g1"), \
             patch.object(_ps, "make_comment", return_value="c"), \
             patch.object(_ps, "update_position_group", side_effect=ConnectionError("redis down")), \
             patch.object(_ps, "send_market_order",
                          return_value=({"price": 2000.0, "volume": 0.05}, None)) as mock_send:
            _ps.handle_position_update(pubsub)
        mock_send.assert_called_once()
        assert _ps.pre_order_volume == Decimal("0")
        assert redis.get("sync_pending_flag") == b"1"

    def test_probe_fill_arms_guard_before_bookkeeping(self):
        redis = FakeRedis({"grid_bot_enabled_flag": b"1", "grid_bot_recovery_flag": b"{}"})
        pubsub = MagicMock()
        pubsub.listen.return_value = iter([_message(5)])
        with patch.object(_ps, "get_redis_connection", return_value=redis), \
             patch.object(_ps, "get_hedge_position", return_value={"volume": "0"}), \
             patch.object(_ps, "resolve_group_id", return_value="g1"), \
             patch.object(_ps, "make_comment", return_value="c"), \
             patch.object(_ps, "update_position_group", side_effect=ConnectionError("redis down")), \
             patch.object(_ps, "send_market_order", return_value=_FILLED):
            _ps.handle_position_update(pubsub)
        assert _ps.pre_order_volume == Decimal("0")
        assert redis.get("grid_bot_recovery_flag") is None


# ---------------------------------------------------------------------------
# utils/api/positions.py: strict fetch
# ---------------------------------------------------------------------------

_pos_spec = importlib.util.spec_from_file_location(
    "_real_positions", pathlib.Path(__file__).parents[4] / "utils" / "api" / "positions.py")
_pos = importlib.util.module_from_spec(_pos_spec)
_pos_spec.loader.exec_module(_pos)


class TestStrictPositionsFetch:

    def _failing_get(self, *a, **k):
        raise _pos.requests.exceptions.ConnectionError("MT5 down")

    def test_default_returns_empty_on_failure(self):
        with patch.object(_pos.requests, "get", side_effect=self._failing_get):
            assert _pos.get_positions().empty

    def test_strict_raises_on_failure(self):
        with patch.object(_pos.requests, "get", side_effect=self._failing_get):
            with pytest.raises(_pos.PositionsUnavailable):
                _pos.get_positions(strict=True)

    def test_strict_raises_on_error_payload(self):
        resp = MagicMock()
        resp.json.return_value = {"error": "MT5 unavailable"}
        with patch.object(_pos.requests, "get", return_value=resp):
            with pytest.raises(_pos.PositionsUnavailable):
                _pos.get_positions(strict=True)

    def test_strict_empty_list_is_a_real_flat_position(self):
        resp = MagicMock()
        resp.json.return_value = []
        with patch.object(_pos.requests, "get", return_value=resp):
            assert _pos.get_positions(strict=True).empty

    def test_hedge_position_read_does_not_turn_failure_into_zero(self):
        redis = FakeRedis()
        with patch.object(_pos, "get_redis_connection", return_value=redis), \
             patch.object(_pos.requests, "get", side_effect=self._failing_get):
            with pytest.raises(_pos.PositionsUnavailable):
                _pos.get_position_by_symbol(HEDGE)
