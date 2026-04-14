import threading
import time

# Single lock that serialises every MT5 API call.
# The background poll thread holds this for each poll cycle (~50 ms when healthy).
# Direct MT5 callers (order routes) must acquire it with a timeout so they fail
# fast instead of blocking indefinitely when MT5 is hung.
mt5_lock = threading.Lock()

# --- cache -----------------------------------------------------------------
_cache_lock = threading.RLock()
_positions_cache: list = []       # list of position dicts
_ticks_cache: dict = {}           # symbol -> tick dict

# --- symbol registration for tick polling ----------------------------------
_poll_symbols_lock = threading.Lock()
_poll_symbols: set = set()

# --- heartbeat -------------------------------------------------------------
# Initialised to startup time so poll_age() starts at 0.
_last_poll_ts: float = time.monotonic()

# --- tunables --------------------------------------------------------------
WATCHDOG_TIMEOUT = 30.0   # seconds — exit if no successful poll
LOCK_TIMEOUT = 15.0       # seconds — max wait on mt5_lock for order routes


# ---------------------------------------------------------------------------
# Cache writers (called from background poll thread)
# ---------------------------------------------------------------------------

def update_positions(positions: list) -> None:
    global _last_poll_ts
    with _cache_lock:
        _positions_cache.clear()
        _positions_cache.extend(positions)
    _last_poll_ts = time.monotonic()


def update_tick(symbol: str, tick: dict) -> None:
    with _cache_lock:
        _ticks_cache[symbol] = tick


# ---------------------------------------------------------------------------
# Cache readers (called from Flask request threads)
# ---------------------------------------------------------------------------

def get_positions() -> list:
    with _cache_lock:
        return list(_positions_cache)


def get_tick(symbol: str):
    with _cache_lock:
        return _ticks_cache.get(symbol)


# ---------------------------------------------------------------------------
# Symbol registration
# ---------------------------------------------------------------------------

def register_symbol(symbol: str) -> None:
    with _poll_symbols_lock:
        _poll_symbols.add(symbol)


def get_poll_symbols() -> list:
    with _poll_symbols_lock:
        return list(_poll_symbols)


# ---------------------------------------------------------------------------
# Health / watchdog helpers
# ---------------------------------------------------------------------------

def poll_age() -> float:
    """Seconds since the last successful background poll."""
    return time.monotonic() - _last_poll_ts
