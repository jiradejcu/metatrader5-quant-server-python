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



def resolve_group_id(redis_conn, symbol: str, is_new_position: bool) -> str:
    """
    Return the group_id to use for the *next* MT5 order on *symbol*.

    - If *is_new_position* is ``True`` (hedge volume was zero before this
      order), a brand-new group_id is generated and stored in Redis.
    - Otherwise the existing group_id is returned (or a new one is minted if
      Redis data is unexpectedly missing).
    """
    if is_new_position:
        group_id = _new_group_id()
        logger.info("[PositionGroup] %s new group started: group_id=%s", symbol, group_id)
        # Pre-seed the Redis key so group_id is available even before the fill
        # comes back.  volume/cost will be populated by update_position_group().
        seed = {"group_id": group_id, "entry_price": 0.0, "volume": 0.0, "cost": 0.0}
        redis_conn.set(_key(symbol), json.dumps(seed))
        return group_id

    existing = get_position_group(redis_conn, symbol)
    if existing and existing.get("group_id"):
        return existing["group_id"]

    # Fallback: Redis was flushed or service restarted mid-position.
    # Mint a new ID and log a warning so the operator knows reconstruction
    # from MT5 history may be needed.
    group_id = _new_group_id()
    logger.warning(
        "[PositionGroup] %s: no existing group in Redis for a non-new position. "
        "Minting recovery group_id=%s — MT5 history reconstruction may be needed.",
        symbol,
        group_id,
    )
    seed = {"group_id": group_id, "entry_price": 0.0, "volume": 0.0, "cost": 0.0}
    redis_conn.set(_key(symbol), json.dumps(seed))
    return group_id


def update_position_group(
    redis_conn,
    symbol: str,
    fill_price: float,
    fill_volume: float,
    is_opening: bool,
    group_id: Optional[str] = None,
) -> float:
    """
    Record a new fill into the position group and return the updated entry price.

    Parameters
    ----------
    redis_conn  : Redis client
    symbol      : MT5 hedge symbol (e.g. ``"XAUUSD"``)
    fill_price  : Actual fill price returned by MT5 (``order['price']``)
    fill_volume : Absolute fill volume in lots (``abs(order['volume'])``)
    is_opening  : ``True`` when the fill *increases* the absolute position size
                  (opening or adding); ``False`` when it *decreases* it (closing).
    group_id    : The group_id resolved before the order was placed.  If
                  ``None``, the value already in Redis is kept.

    Returns
    -------
    float
        The current group entry price after the update (0.0 if the group was
        reset because the position is now fully closed).
    """
    existing = get_position_group(redis_conn, symbol)
    # Prefer the caller-supplied group_id; fall back to what is in Redis.
    resolved_id = group_id or (existing.get("group_id") if existing else _new_group_id())

    if is_opening:
        if existing is None or float(existing.get("volume", 0)) == 0.0:
            # Brand-new or just seeded group
            group = {
                "group_id": resolved_id,
                "entry_price": fill_price,
                "volume": fill_volume,
                "cost": fill_price * fill_volume,
            }
        else:
            prev_cost = float(existing["cost"])
            prev_volume = float(existing["volume"])
            new_cost = prev_cost + fill_price * fill_volume
            new_volume = prev_volume + fill_volume
            group = {
                "group_id": resolved_id,
                "entry_price": new_cost / new_volume if new_volume > 0 else 0.0,
                "volume": new_volume,
                "cost": new_cost,
            }

        redis_conn.set(_key(symbol), json.dumps(group))
        logger.info(
            "[PositionGroup] %s OPEN fill: group_id=%s price=%.5f vol=%.5f → "
            "group_entry=%.5f group_vol=%.5f",
            symbol, resolved_id, fill_price, fill_volume,
            group["entry_price"], group["volume"],
        )
        return group["entry_price"]

    # --- Closing fill ---
    if existing is None:
        logger.warning(
            "[PositionGroup] %s: closing fill received but no group found in Redis.",
            symbol,
        )
        return 0.0

    prev_volume = float(existing["volume"])
    new_volume = max(prev_volume - fill_volume, 0.0)

    if new_volume <= 1e-9:
        # Position fully closed — reset
        redis_conn.delete(_key(symbol))
        logger.info(
            "[PositionGroup] %s group_id=%s fully closed — group reset.",
            symbol, resolved_id,
        )
        return 0.0

    group = {
        "group_id": resolved_id,
        "entry_price": float(existing["entry_price"]),
        "volume": new_volume,
        # Recompute cost from entry price so future opens blend correctly
        "cost": float(existing["entry_price"]) * new_volume,
    }
    redis_conn.set(_key(symbol), json.dumps(group))
    logger.info(
        "[PositionGroup] %s CLOSE fill: group_id=%s vol=%.5f remaining=%.5f "
        "group_entry UNCHANGED=%.5f",
        symbol, resolved_id, fill_volume, new_volume, group["entry_price"],
    )
    return float(existing["entry_price"])


def reset_position_group(redis_conn, symbol: str) -> None:
    """Forcefully clear the position group for *symbol* (e.g. on manual close)."""
    redis_conn.delete(_key(symbol))
    logger.info("[PositionGroup] %s group forcefully reset.", symbol)
