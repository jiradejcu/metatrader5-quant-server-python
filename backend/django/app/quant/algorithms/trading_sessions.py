import json
import logging
from datetime import datetime, timezone

from app.utils.redis_client import get_redis_connection

logger = logging.getLogger(__name__)

_DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def is_within_trading_session(primary_symbol, hedge_symbol):
    """Return True if current UTC time falls within a configured trading session window.

    If no session config is stored in Redis, returns True (unrestricted).
    Time ranges use "HH:MM" strings; "24:00" means end of day.

    Shared by grid_bot (trades only inside the window) and prediction_bot
    (trades only outside it), so the two stay interlocked off one source of
    truth instead of drifting apart.
    """
    try:
        redis_conn = get_redis_connection()
        key = f"trading_sessions:{primary_symbol}:{hedge_symbol}"
        raw = redis_conn.get(key)
        if not raw:
            return True

        sessions = json.loads(raw)
        now_utc = datetime.now(timezone.utc)
        day_name = _DAY_NAMES[now_utc.weekday()]
        ranges = sessions.get(day_name, [])

        current_minutes = now_utc.hour * 60 + now_utc.minute

        for r in ranges:
            start_h, start_m = map(int, r['start'].split(':'))
            end_h, end_m = map(int, r['end'].split(':'))
            start_min = start_h * 60 + start_m
            end_min = end_h * 60 + end_m  # 24:00 → 1440, always > any valid time
            if start_min <= current_minutes < end_min:
                return True

        return False
    except Exception as e:
        logger.warning(f"[Session] Failed to check trading session, allowing tick: {e}")
        return True
