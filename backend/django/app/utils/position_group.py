"""
Position Group Entry Price Tracker
===================================
Maintains a running VWAP entry price for the MT5 hedge position that mirrors
how Binance computes its ``entryPrice``:

  - On an **opening** fill (absolute position size increases): update the VWAP.
  - On a **closing** fill (absolute position size decreases): keep the VWAP unchanged.
  - When the position is fully closed: clear the group.

Each group is assigned a unique ``group_id`` (Unix-timestamp string) that is
embedded in the MT5 order ``comment`` field of every order belonging to that
position lifecycle.  This gives two important properties:

  1. **Durability** – the group membership is stored inside MT5 itself (not
     only in Redis), so it survives service restarts and Redis flushes.
  2. **Reconstructability** – you can call MT5 deal-history filtered by
     ``comment`` containing the group_id to recalculate the group VWAP from
     scratch at any time.

Redis key format: ``position_group:{symbol}``

Stored JSON schema::

    {
        "group_id":    <str>,    # e.g. "1716000000"  — embedded in MT5 comment
        "entry_price": <float>,  # VWAP of all opening fills
        "volume":      <float>,  # Running absolute volume (MT5 lots)
        "cost":        <float>   # Running notional (sum price*volume for opens)
    }

MT5 comment convention: ``"grp:{group_id}"``  (≤ 14 chars, fits within MT5's
31-char comment limit).
"""

import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

_KEY_PREFIX = "position_group"


def _key(symbol: str) -> str:
    return f"{_KEY_PREFIX}:{symbol}"


def _new_group_id() -> str:
    """Generate a short, unique group ID from the current Unix timestamp."""
    return str(int(time.time()))


def make_comment(group_id: str) -> str:
    """Return the MT5 comment string for *group_id*. e.g. ``'grp:1716000000'``."""
    return f"grp:{group_id}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_position_group(redis_conn, symbol: str) -> Optional[dict]:
    """Return the raw group dict for *symbol*, or ``None`` if not tracked."""
    raw = redis_conn.get(_key(symbol))
    return json.loads(raw) if raw else None


def get_position_group_id(redis_conn, symbol: str) -> Optional[str]:
    """Return the active ``group_id`` for *symbol*, or ``None``."""
    group = get_position_group(redis_conn, symbol)
    return group.get("group_id") if group else None


def resolve_group_id(redis_conn, symbol: str) -> str:
    """
    Return the group_id to use for the *next* MT5 order on *symbol*.

    Returns the existing group_id from Redis, or creates and seeds a new one
    if none exists (new position, Redis flush, or service restart).
    """
    existing = get_position_group(redis_conn, symbol)
    if existing and existing.get("group_id"):
        return existing["group_id"]

    group_id = _new_group_id()
    logger.info("[PositionGroup] %s new group started: group_id=%s", symbol, group_id)
    seed = {"group_id": group_id, "entry_price": 0.0, "volume": 0.0, "cost": 0.0}
    redis_conn.set(_key(symbol), json.dumps(seed))
    return group_id


def update_position_group(
    redis_conn,
    symbol: str,
    fill_price: float,
    fill_volume: float,
    group_id: str,
) -> float:
    """
    Record a new fill into the position group and return the updated entry price.

    fill_volume is signed: positive = opening/adding, negative = closing/reducing.
    VWAP is updated only on positive fills; preserved on negative fills.
    Deletes the group when new_volume reaches zero.
    """
    existing = get_position_group(redis_conn, symbol)
    prev_volume = float(existing["volume"]) if existing else 0.0
    prev_cost = float(existing["cost"]) if existing else 0.0
    prev_entry = float(existing["entry_price"]) if existing else 0.0

    new_volume = prev_volume + fill_volume

    if new_volume <= 1e-9:
        redis_conn.delete(_key(symbol))
        if existing is None and fill_volume < 0:
            logger.warning("[PositionGroup] %s group_id=%s closing fill but no group in Redis.", symbol, group_id)
        else:
            logger.info("[PositionGroup] %s group_id=%s fully closed — group reset.", symbol, group_id)
        return 0.0

    if fill_volume > 0:
        new_cost = prev_cost + fill_price * fill_volume
        entry_price = new_cost / new_volume
    else:
        new_cost = prev_entry * new_volume
        entry_price = prev_entry

    group = {
        "group_id": group_id,
        "entry_price": entry_price,
        "volume": new_volume,
        "cost": new_cost,
    }
    redis_conn.set(_key(symbol), json.dumps(group))
    logger.info(
        "[PositionGroup] %s %s fill: group_id=%s price=%.5f vol=%.5f → "
        "group_entry=%.5f group_vol=%.5f",
        symbol, "OPEN" if fill_volume > 0 else "CLOSE",
        group_id, fill_price, fill_volume, entry_price, new_volume,
    )
    return entry_price
