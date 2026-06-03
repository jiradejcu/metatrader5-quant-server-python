"""
Unit tests for app.utils.position_group
========================================
All Redis calls are intercepted with a lightweight fake that keeps data in a
plain dict — no real Redis connection required.
"""
import json
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

from app.utils.position_group import (
    get_position_group,
    get_position_group_id,
    resolve_group_id,
    update_position_group,
    reset_position_group,
    make_comment,
    _key,
)

# ---------------------------------------------------------------------------
# Fake Redis — stores raw bytes keyed by string
# ---------------------------------------------------------------------------

class FakeRedis:
    """Minimal Redis stub: get / set / delete."""

    def __init__(self, initial: dict = None):
        self._store: dict[str, bytes] = {}
        if initial:
            for k, v in initial.items():
                self._store[k] = json.dumps(v).encode()

    def get(self, key: str):
        return self._store.get(key)

    def set(self, key: str, value):
        self._store[key] = value if isinstance(value, bytes) else value.encode()

    def delete(self, key: str):
        self._store.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self._store

    # Convenience helpers for test assertions
    def load(self, key: str):
        raw = self._store.get(key)
        return json.loads(raw) if raw else None


SYMBOL = "XAUUSD"
KEY = _key(SYMBOL)


# ---------------------------------------------------------------------------
# make_comment
# ---------------------------------------------------------------------------

class TestMakeComment:

    def test_format(self):
        assert make_comment("1716000000") == "grp:1716000000"

    def test_within_mt5_comment_limit(self):
        comment = make_comment("1716000000")
        assert len(comment) <= 31  # MT5 comment field limit


# ---------------------------------------------------------------------------
# get_position_group
# ---------------------------------------------------------------------------

class TestGetPositionGroup:

    def test_returns_none_when_no_key(self):
        r = FakeRedis()
        assert get_position_group(r, SYMBOL) is None

    def test_returns_dict_when_key_present(self):
        data = {"group_id": "111", "entry_price": 2000.0, "volume": 1.0, "cost": 2000.0}
        r = FakeRedis({KEY: data})
        result = get_position_group(r, SYMBOL)
        assert result == data


# ---------------------------------------------------------------------------
# get_position_group_id
# ---------------------------------------------------------------------------

class TestGetPositionGroupId:

    def test_returns_none_when_no_key(self):
        r = FakeRedis()
        assert get_position_group_id(r, SYMBOL) is None

    def test_returns_group_id(self):
        r = FakeRedis({KEY: {"group_id": "abc123", "entry_price": 0.0, "volume": 0.0, "cost": 0.0}})
        assert get_position_group_id(r, SYMBOL) == "abc123"


# ---------------------------------------------------------------------------
# resolve_group_id
# ---------------------------------------------------------------------------

class TestResolveGroupId:

    def test_no_existing_group_generates_fresh_id(self):
        r = FakeRedis()
        with patch("app.utils.position_group._new_group_id", return_value="NEW_GRP"):
            gid = resolve_group_id(r, SYMBOL)
        assert gid == "NEW_GRP"

    def test_no_existing_group_pre_seeds_redis(self):
        r = FakeRedis()
        with patch("app.utils.position_group._new_group_id", return_value="SEED"):
            resolve_group_id(r, SYMBOL)
        stored = r.load(KEY)
        assert stored["group_id"] == "SEED"
        assert stored["entry_price"] == 0.0
        assert stored["volume"] == 0.0
        assert stored["cost"] == 0.0

    def test_existing_group_returns_existing_id(self):
        r = FakeRedis({KEY: {"group_id": "EXIST", "entry_price": 1800.0, "volume": 2.0, "cost": 3600.0}})
        gid = resolve_group_id(r, SYMBOL)
        assert gid == "EXIST"

    def test_seeds_redis_when_no_group_found(self):
        r = FakeRedis()
        with patch("app.utils.position_group._new_group_id", return_value="RECOVER"):
            gid = resolve_group_id(r, SYMBOL)
        assert gid == "RECOVER"
        stored = r.load(KEY)
        assert stored["group_id"] == "RECOVER"


# ---------------------------------------------------------------------------
# update_position_group — opening fills
# ---------------------------------------------------------------------------

class TestUpdatePositionGroupOpeningFills:

    def test_first_open_sets_entry_price_to_fill_price(self):
        r = FakeRedis()
        entry = update_position_group(r, SYMBOL, fill_price=2000.0, fill_volume=1.0,
                                      is_opening=True, group_id="G1")
        assert entry == pytest.approx(2000.0)

    def test_first_open_stores_correct_group(self):
        r = FakeRedis()
        update_position_group(r, SYMBOL, fill_price=2000.0, fill_volume=1.0,
                              is_opening=True, group_id="G1")
        stored = r.load(KEY)
        assert stored["group_id"] == "G1"
        assert stored["entry_price"] == pytest.approx(2000.0)
        assert stored["volume"] == pytest.approx(1.0)
        assert stored["cost"] == pytest.approx(2000.0)

    def test_second_open_vwap_recalculates(self):
        """Two fills at different prices → VWAP = (p1*v1 + p2*v2) / (v1+v2)."""
        r = FakeRedis()
        update_position_group(r, SYMBOL, fill_price=2000.0, fill_volume=1.0,
                              is_opening=True, group_id="G1")
        # Second fill: price=2100, vol=1 → VWAP = (2000+2100)/2 = 2050
        entry = update_position_group(r, SYMBOL, fill_price=2100.0, fill_volume=1.0,
                                      is_opening=True, group_id="G1")
        assert entry == pytest.approx(2050.0)

    def test_vwap_weights_by_volume(self):
        """Larger second fill should pull VWAP towards its price."""
        r = FakeRedis()
        update_position_group(r, SYMBOL, fill_price=2000.0, fill_volume=1.0,
                              is_opening=True, group_id="G1")
        # Second fill: price=2200, vol=3 → VWAP = (2000*1 + 2200*3) / 4 = 2150
        entry = update_position_group(r, SYMBOL, fill_price=2200.0, fill_volume=3.0,
                                      is_opening=True, group_id="G1")
        assert entry == pytest.approx(2150.0)

    def test_three_open_fills_vwap(self):
        r = FakeRedis()
        update_position_group(r, SYMBOL, fill_price=1800.0, fill_volume=2.0,
                              is_opening=True, group_id="G1")
        update_position_group(r, SYMBOL, fill_price=1900.0, fill_volume=1.0,
                              is_opening=True, group_id="G1")
        entry = update_position_group(r, SYMBOL, fill_price=2000.0, fill_volume=1.0,
                                      is_opening=True, group_id="G1")
        # (1800*2 + 1900*1 + 2000*1) / 4 = 7500/4 = 1875
        assert entry == pytest.approx(1875.0)

    def test_first_open_on_seeded_empty_group(self):
        """resolve_group_id pre-seeds volume=0; first fill should treat it as brand-new."""
        r = FakeRedis({KEY: {"group_id": "G1", "entry_price": 0.0, "volume": 0.0, "cost": 0.0}})
        entry = update_position_group(r, SYMBOL, fill_price=1950.0, fill_volume=0.5,
                                      is_opening=True, group_id="G1")
        assert entry == pytest.approx(1950.0)
        stored = r.load(KEY)
        assert stored["volume"] == pytest.approx(0.5)

    def test_open_without_group_id_uses_redis_id(self):
        """Caller omits group_id → should use whatever is already in Redis."""
        r = FakeRedis({KEY: {"group_id": "REDIS_GRP", "entry_price": 0.0, "volume": 0.0, "cost": 0.0}})
        update_position_group(r, SYMBOL, fill_price=2000.0, fill_volume=1.0, is_opening=True)
        stored = r.load(KEY)
        assert stored["group_id"] == "REDIS_GRP"


# ---------------------------------------------------------------------------
# update_position_group — closing fills
# ---------------------------------------------------------------------------

class TestUpdatePositionGroupClosingFills:

    def _seed(self, r, entry_price=2000.0, volume=2.0, group_id="G1"):
        cost = entry_price * volume
        r.set(KEY, json.dumps({
            "group_id": group_id,
            "entry_price": entry_price,
            "volume": volume,
            "cost": cost,
        }))

    def test_partial_close_preserves_entry_price(self):
        r = FakeRedis()
        self._seed(r, entry_price=2000.0, volume=2.0)
        entry = update_position_group(r, SYMBOL, fill_price=2100.0, fill_volume=1.0,
                                      is_opening=False, group_id="G1")
        assert entry == pytest.approx(2000.0)

    def test_partial_close_reduces_volume(self):
        r = FakeRedis()
        self._seed(r, entry_price=2000.0, volume=2.0)
        update_position_group(r, SYMBOL, fill_price=2100.0, fill_volume=1.0,
                              is_opening=False, group_id="G1")
        stored = r.load(KEY)
        assert stored["volume"] == pytest.approx(1.0)

    def test_partial_close_keeps_entry_price_in_redis(self):
        r = FakeRedis()
        self._seed(r, entry_price=2000.0, volume=3.0)
        update_position_group(r, SYMBOL, fill_price=2200.0, fill_volume=1.0,
                              is_opening=False)
        stored = r.load(KEY)
        assert stored["entry_price"] == pytest.approx(2000.0)

    def test_full_close_resets_group(self):
        r = FakeRedis()
        self._seed(r, entry_price=2000.0, volume=1.0)
        entry = update_position_group(r, SYMBOL, fill_price=2100.0, fill_volume=1.0,
                                      is_opening=False, group_id="G1")
        assert entry == pytest.approx(0.0)
        assert r.load(KEY) is None  # key deleted

    def test_full_close_via_tiny_remainder(self):
        """Floating-point remainder ≤ 1e-9 should still trigger a full reset."""
        r = FakeRedis()
        self._seed(r, entry_price=1800.0, volume=1e-10)
        entry = update_position_group(r, SYMBOL, fill_price=1800.0, fill_volume=1e-10,
                                      is_opening=False, group_id="G1")
        assert entry == pytest.approx(0.0)
        assert r.load(KEY) is None

    def test_close_without_group_in_redis_warns_and_returns_zero(self):
        r = FakeRedis()  # empty
        with patch("app.utils.position_group.logger") as mock_log:
            entry = update_position_group(r, SYMBOL, fill_price=2000.0, fill_volume=1.0,
                                          is_opening=False, group_id="G1")
        assert entry == pytest.approx(0.0)
        mock_log.warning.assert_called_once()

    def test_multiple_partial_closes_decrement_volume(self):
        r = FakeRedis()
        self._seed(r, entry_price=2000.0, volume=3.0)
        update_position_group(r, SYMBOL, fill_price=2050.0, fill_volume=1.0, is_opening=False)
        update_position_group(r, SYMBOL, fill_price=2100.0, fill_volume=1.0, is_opening=False)
        stored = r.load(KEY)
        assert stored["volume"] == pytest.approx(1.0)
        assert stored["entry_price"] == pytest.approx(2000.0)  # unchanged throughout


# ---------------------------------------------------------------------------
# update_position_group — mixed lifecycle (open → partial close → reopen)
# ---------------------------------------------------------------------------

class TestUpdatePositionGroupLifecycle:

    def test_open_partial_close_then_reopen_blends_correctly(self):
        """
        Phase 1: open 2 lots @ 2000 → VWAP=2000
        Phase 2: close 1 lot  @ 2100 → VWAP still 2000, vol=1
        Phase 3: open 1 lot   @ 2200 → VWAP=(2000*1 + 2200*1)/2 = 2100
        """
        r = FakeRedis()
        update_position_group(r, SYMBOL, fill_price=2000.0, fill_volume=2.0,
                              is_opening=True, group_id="G1")
        update_position_group(r, SYMBOL, fill_price=2100.0, fill_volume=1.0,
                              is_opening=False, group_id="G1")
        entry = update_position_group(r, SYMBOL, fill_price=2200.0, fill_volume=1.0,
                                      is_opening=True, group_id="G1")
        assert entry == pytest.approx(2100.0)

    def test_full_close_then_new_open_uses_new_price(self):
        """After full close (group deleted), next open starts fresh."""
        r = FakeRedis()
        update_position_group(r, SYMBOL, fill_price=2000.0, fill_volume=1.0,
                              is_opening=True, group_id="G1")
        update_position_group(r, SYMBOL, fill_price=2100.0, fill_volume=1.0,
                              is_opening=False, group_id="G1")
        # Now fully closed — open a new position
        entry = update_position_group(r, SYMBOL, fill_price=2300.0, fill_volume=1.0,
                                      is_opening=True, group_id="G2")
        assert entry == pytest.approx(2300.0)

    def test_group_vwap_not_affected_by_close_price(self):
        """
        The closing trade price must never influence the entry VWAP.
        Open @ 1800 and 1900 → VWAP=1850. Close @ 2500 → VWAP still 1850.
        """
        r = FakeRedis()
        update_position_group(r, SYMBOL, fill_price=1800.0, fill_volume=1.0,
                              is_opening=True, group_id="G1")
        update_position_group(r, SYMBOL, fill_price=1900.0, fill_volume=1.0,
                              is_opening=True, group_id="G1")
        entry = update_position_group(r, SYMBOL, fill_price=2500.0, fill_volume=1.0,
                                      is_opening=False, group_id="G1")
        assert entry == pytest.approx(1850.0)


# ---------------------------------------------------------------------------
# reset_position_group
# ---------------------------------------------------------------------------

class TestResetPositionGroup:

    def test_deletes_key(self):
        r = FakeRedis({KEY: {"group_id": "G1", "entry_price": 2000.0, "volume": 1.0, "cost": 2000.0}})
        reset_position_group(r, SYMBOL)
        assert r.load(KEY) is None

    def test_no_error_when_key_absent(self):
        r = FakeRedis()
        reset_position_group(r, SYMBOL)  # should not raise


# ---------------------------------------------------------------------------
# entryPrice vs currentEntryPrice divergence after partial close
#
# entryPrice        — group VWAP of ALL opening fills; never changes on close.
# currentEntryPrice — live VWAP of remaining open MT5 lots only (mirrors the
#                     formula in subscribe_hedge_position in positions.py):
#
#     current_entry = (price_open * signed_volume).sum()
#                     / signed_volume.sum()
#
# The two values are equal while no lots have been closed, but diverge as soon
# as a specific lot (with its own open price) is closed.
# ---------------------------------------------------------------------------

def _current_entry_price(open_lots: list[dict]) -> float:
    """
    Mirror the currentEntryPrice formula from positions.py:subscribe_hedge_position.

    Each dict in open_lots must have keys:
      price_open   — the price at which the lot was opened
      signed_volume — positive for BUY lots, negative for SELL lots
    """
    df = pd.DataFrame(open_lots)
    total = df["signed_volume"].sum()
    if total == 0.0:
        return 0.0
    return float((df["price_open"] * df["signed_volume"]).sum() / total)


class TestEntryPriceVsCurrentEntryPrice:
    """
    Demonstrates that entryPrice (group VWAP) and currentEntryPrice (remaining
    lots VWAP) are equal before any close but diverge after a specific lot is
    partially closed.
    """

    def test_before_any_close_both_prices_are_equal(self):
        """
        Open two BUY lots at different prices.
        Both group VWAP and current-entry VWAP reflect the same weighted average.
        """
        r = FakeRedis()
        update_position_group(r, SYMBOL, fill_price=1800.0, fill_volume=1.0,
                              is_opening=True, group_id="G1")
        update_position_group(r, SYMBOL, fill_price=2000.0, fill_volume=1.0,
                              is_opening=True, group_id="G1")

        group_entry = r.load(KEY)["entry_price"]                # 1900.0

        open_lots = [
            {"price_open": 1800.0, "signed_volume": 1.0},      # lot A still open
            {"price_open": 2000.0, "signed_volume": 1.0},      # lot B still open
        ]
        current_entry = _current_entry_price(open_lots)         # 1900.0

        assert group_entry == pytest.approx(1900.0)
        assert current_entry == pytest.approx(1900.0)
        assert group_entry == pytest.approx(current_entry)      # equal before close

    def test_after_partial_close_prices_diverge(self):
        """
        Open lot A @ 1800, lot B @ 2000 → group VWAP = 1900.
        Close lot A (the cheaper one).

        entryPrice        stays at 1900 (group VWAP never changes on close).
        currentEntryPrice becomes 2000 (only lot B remains, opened at 2000).

        The two values are now different.
        """
        r = FakeRedis()
        update_position_group(r, SYMBOL, fill_price=1800.0, fill_volume=1.0,
                              is_opening=True, group_id="G1")
        update_position_group(r, SYMBOL, fill_price=2000.0, fill_volume=1.0,
                              is_opening=True, group_id="G1")

        # Close lot A — group VWAP must remain unchanged
        group_entry_after_close = update_position_group(
            r, SYMBOL, fill_price=2100.0, fill_volume=1.0,
            is_opening=False, group_id="G1",
        )

        # Only lot B is still open
        open_lots = [
            {"price_open": 2000.0, "signed_volume": 1.0},
        ]
        current_entry = _current_entry_price(open_lots)

        assert group_entry_after_close == pytest.approx(1900.0)  # unchanged group VWAP
        assert current_entry == pytest.approx(2000.0)            # only lot B remains
        assert group_entry_after_close != pytest.approx(current_entry)  # they differ

    def test_after_partial_close_prices_diverge_opposite_direction(self):
        """
        Same setup but close the *more expensive* lot B instead.

        entryPrice        stays at 1900 (unchanged).
        currentEntryPrice becomes 1800 (only lot A remains).

        Gap is now in the opposite direction: group VWAP > current entry.
        """
        r = FakeRedis()
        update_position_group(r, SYMBOL, fill_price=1800.0, fill_volume=1.0,
                              is_opening=True, group_id="G1")
        update_position_group(r, SYMBOL, fill_price=2000.0, fill_volume=1.0,
                              is_opening=True, group_id="G1")

        group_entry_after_close = update_position_group(
            r, SYMBOL, fill_price=2100.0, fill_volume=1.0,
            is_opening=False, group_id="G1",
        )

        # Only lot A (opened at 1800) remains
        open_lots = [
            {"price_open": 1800.0, "signed_volume": 1.0},
        ]
        current_entry = _current_entry_price(open_lots)

        assert group_entry_after_close == pytest.approx(1900.0)  # unchanged group VWAP
        assert current_entry == pytest.approx(1800.0)            # only lot A remains
        assert group_entry_after_close > current_entry           # group VWAP > current entry

    def test_three_lots_partial_close_shows_divergence(self):
        """
        Open 3 lots at 1800 / 1900 / 2000 → group VWAP = 1900.
        Close the 1800 lot.

        entryPrice        = 1900 (unchanged).
        currentEntryPrice = (1900*1 + 2000*1) / 2 = 1950 (remaining 2 lots).
        """
        r = FakeRedis()
        update_position_group(r, SYMBOL, fill_price=1800.0, fill_volume=1.0,
                              is_opening=True, group_id="G1")
        update_position_group(r, SYMBOL, fill_price=1900.0, fill_volume=1.0,
                              is_opening=True, group_id="G1")
        update_position_group(r, SYMBOL, fill_price=2000.0, fill_volume=1.0,
                              is_opening=True, group_id="G1")

        group_entry_after_close = update_position_group(
            r, SYMBOL, fill_price=2200.0, fill_volume=1.0,
            is_opening=False, group_id="G1",
        )

        # Lots B and C remain
        open_lots = [
            {"price_open": 1900.0, "signed_volume": 1.0},
            {"price_open": 2000.0, "signed_volume": 1.0},
        ]
        current_entry = _current_entry_price(open_lots)

        assert group_entry_after_close == pytest.approx(1900.0)  # unchanged
        assert current_entry == pytest.approx(1950.0)            # remaining lots only
        assert group_entry_after_close != pytest.approx(current_entry)
