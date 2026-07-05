#!/usr/bin/env python3
"""
Replay real historical ticks from a quant log through the *real* grid bot.

Unlike replay_atr.py (which only re-runs the ATR math) this runs the actual
``handle_grid_flow`` / ``_process_tick`` / ``_reconcile`` code with the Binance
API mocked, so every trading decision is reproduced. It writes a *new* log in
the exact production format, which you can then chart with plots.py and diff
against the original run.

Typical workflow — compare a parameter/logic change:

  # 1. Baseline replay of the recorded ticks
  PAIR_INDEX auto-detected from the log's "Price diff for X/Y" line.
  python app/quant/algorithms/arbitrage/tests/replay_bot.py \
      /app/logs/quant.log.2026-07-01.123000_to_124500.log \
      --output /app/logs/replay_baseline.log

  # 2. Change a param (env for ATR_*, or edit grid_bot.py logic) and replay again
  ATR_HIGH_THRESHOLD=0.4 python .../replay_bot.py <same input> \
      --output /app/logs/replay_atr0.4.log

  # 3. Chart both and compare
  python app/utils/plots.py --atr /app/logs/replay_baseline.log
  python app/utils/plots.py --atr /app/logs/replay_atr0.4.log

Fill model: SIMULATE. The starting position is seeded from the log's first
``position=`` line; the bot's own orders then fill (``--fill-pct``, default 1.0
= full fill) and evolve the position. So a changed param actually changes the
trade path. Fills are idealized (your orders are assumed to fill) — see README.

Isolation: fully self-contained. It uses an in-process pub/sub bus instead of
real Redis (so no Redis/live infra is required and it can never touch live
channels), neutralises the active/sync/session gates, mocks all Binance calls,
and writes only to the output log — never the production quant.log.

Fidelity notes / limitations:
  * ATR is reproduced exactly (it is order-based, computed per tick).
  * Grid limits follow the recorded timeline: initial limits are reconstructed
    from the first ``Zone=`` line (+ ``max_pos=`` and order size), then each
    ``[PubSub] Grid settings updated`` line is re-applied at its point in the
    stream.
  * Stale-price aborts are NOT reproduced: staleness is wall-clock based and
    every replayed tick is processed immediately, so age ~= 0. Gaps in the live
    feed (which caused real staleness) simply appear as absent ticks here.
"""

import os
import re
import sys
import ast
import json
import time
import queue
import logging
import argparse
import threading
from types import SimpleNamespace
from datetime import datetime

# ---------------------------------------------------------------------------
# Django setup (must happen before any app.* import)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../../")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
import django  # noqa: E402
django.setup()

import app.quant.algorithms.arbitrage.grid_bot as grid_bot  # noqa: E402
import app.quant.algorithms.arbitrage.config as config  # noqa: E402

# Publisher-side log lines carry this name so plots.py's price_diff regexes
# match them (it keys on ".../price_diff").
pub_log = logging.getLogger("app.quant.algorithms.arbitrage.price_diff")
# Simulated fills are logged under the real user-data-stream name and in the
# exact "[UserDataStream] Order ...: side=... qty=.../..." shape so plots.py's
# fills overlay picks them up. fill_price isn't tracked in replay (the log only
# has diffs, not absolute prices) and plots.py positions fills by the diff at
# fill time anyway, so a 0.0 placeholder is fine.
fill_log = logging.getLogger("app.connectors.binance.api.user_data_stream")


# ---------------------------------------------------------------------------
# In-process pub/sub bus — a drop-in for the tiny slice of the Redis API the
# grid bot uses (pubsub/listen/publish + get/set/expire). Keeps replay fully
# offline and unable to touch live channels.
# ---------------------------------------------------------------------------
class _FakeBus:
    def __init__(self):
        self._subs = {}   # channel(str) -> list[queue.Queue]
        self._lock = threading.Lock()

    def register(self, channel, q):
        with self._lock:
            self._subs.setdefault(channel, []).append(q)

    def publish(self, channel, data):
        if isinstance(data, str):
            data = data.encode()
        with self._lock:
            targets = list(self._subs.get(channel, []))
        for q in targets:
            q.put((channel, data))


class _FakePubSub:
    def __init__(self, bus):
        self._bus = bus
        self._q = queue.Queue()

    def subscribe(self, *channels):
        for c in channels:
            self._bus.register(c, self._q)

    def listen(self):
        while True:
            channel, data = self._q.get()
            # Match real redis-py: channel/data are bytes, type is 'message'.
            yield {"type": "message", "channel": channel.encode(), "data": data}


class _FakeRedis:
    """The handful of Redis calls grid_bot makes, backed by memory."""
    def __init__(self):
        self._store = {}
        self._bus = _FakeBus()

    def pubsub(self):
        return _FakePubSub(self._bus)

    def publish(self, channel, data):
        self._bus.publish(channel, data)

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value, *args, **kwargs):
        self._store[key] = value.encode() if isinstance(value, str) else value

    def expire(self, *args, **kwargs):
        pass


# ---------------------------------------------------------------------------
# Simulated market — position evolves from the bot's own (mocked) fills
# ---------------------------------------------------------------------------
_market = {
    "position": 0.0,
    "open_orders": [],   # list of SimpleNamespace(order_id, side, orig_qty)
    "fill_pct": 1.0,     # 0.0 = no fill, 0.5 = partial, 1.0 = full
    "ask": 1.0,          # latest primary ask/bid (absolute price) for fill_price
    "bid": 1.0,
}
_order_counter = 0


def mock_cancel_all_open_orders(symbol):
    _market["open_orders"].clear()
    return None


def mock_chase_order(symbol, quantity, side, order_id=None):
    global _order_counter
    if order_id is not None:
        # Modify/chase path — order already resting, just re-price it.
        return SimpleNamespace(order_id=order_id)

    _order_counter += 1
    oid = f"SIM_{_order_counter:04d}"
    fill_pct = _market["fill_pct"]
    filled_qty = round(quantity * fill_pct, 8)
    remaining_qty = round(quantity - filled_qty, 8)

    delta = filled_qty if side == "BUY" else -filled_qty
    _market["position"] = round(_market["position"] + delta, 8)

    if remaining_qty > 0:
        status = "PARTIALLY_FILLED" if fill_pct > 0 else "NEW"
        _market["open_orders"].append(
            SimpleNamespace(order_id=oid, side=side, orig_qty=remaining_qty)
        )
    else:
        status = "FILLED"

    if filled_qty > 0:
        # Mirror the user-data-stream fill line so plots.py's overlay counts it.
        # BUY lifts the ask, SELL hits the bid (absolute primary price).
        price = _market["ask"] if side == "BUY" else _market["bid"]
        fill_log.info(
            f"[UserDataStream] Order {status}: side={side} "
            f"fill_price={price} avg_price={price} qty={filled_qty}/{quantity} order_id={oid}"
        )
    return SimpleNamespace(order_id=oid, status=status, orig_qty=quantity, side=side)


def mock_get_open_orders(symbol, force=False):
    return list(_market["open_orders"])


def mock_get_position(symbol, force=False):
    return {"positionAmt": str(_market["position"])}


def patch_grid_bot(fake_redis):
    """Replace exchange I/O and neutralise the live gates for isolated replay."""
    grid_bot.cancel_all_open_orders = mock_cancel_all_open_orders
    grid_bot.chase_order = mock_chase_order
    grid_bot.get_open_orders = mock_get_open_orders
    grid_bot.get_position = mock_get_position
    # Point the bot's own Redis lookups (initial settings fetch) at our fake.
    grid_bot.get_redis_connection = lambda: fake_redis
    # Gates that would otherwise depend on live Redis flags / wall-clock session.
    grid_bot.get_active_status = lambda: True
    grid_bot.get_position_sync_ok = lambda: True
    grid_bot.get_sync_pending = lambda: False
    grid_bot._is_within_trading_session = lambda *a, **k: True


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------
_TS = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"

_PRICE_RE = re.compile(
    _TS + r".*?price_diff:compare.*?Price diff for [^:]+:\s*(\{.*\})\s*$"
)
_SETTINGS_RE = re.compile(
    _TS + r".*\[PubSub\] Grid settings updated:\s*(\{.*\})\s*$"
)
_ZONE_RE = re.compile(
    r"long_exit>=([\d.]+), short_entry>=([\d.]+)\), "
    r"bid_diff=[-\d.]+ \(short_exit<=([\d.]+), long_entry<=([\d.]+)"
)
_MAXPOS_RE = re.compile(r"max_pos=([\d.]+)")
_POSITION_RE = re.compile(r"position=([+-]?[\d.]+) open_orders=")
_PLACING_RE = re.compile(r"placing (?:BUY|SELL), size=([\d.]+)")

# Keys as grid_bot._parse_grid_settings expects them in the raw Redis payload.
_RAW_KEYS = {
    "long_upper": "long_upper_limit",
    "long_lower": "long_lower_limit",
    "short_upper": "short_upper_limit",
    "short_lower": "short_lower_limit",
    "max_position_size": "max_position_size",
    "order_size": "order_size",
}


def _to_raw_payload(parsed):
    """Turn a parsed settings dict (grid_bot's log form) into a Redis payload."""
    return {raw: parsed[key] for key, raw in _RAW_KEYS.items()}


def parse_log(path, default_order_size):
    """Return (events, initial_settings, initial_position, primary, hedge).

    events is an ordered list of (kind, data, wall_dt):
        ("tick",     {"ask": .., "bid": .., "ts": ..},  datetime)
        ("settings", raw_payload_dict,                  datetime)
    reflecting the chronological stream the live bot consumed. wall_dt is the
    original log timestamp, used to re-stamp the replay log onto the source
    timeline.
    """
    events = []
    initial_settings = None            # reconstructed limits in effect at t=start
    initial_position = None
    primary = hedge = None
    seen_order_size = None
    first_max_pos = None

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")

            m = _PRICE_RE.search(line)
            if m:
                try:
                    d = ast.literal_eval(m.group(2))
                except (ValueError, SyntaxError):
                    continue
                wall = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f")
                if primary is None:
                    primary = d.get("primary_symbol")
                    hedge = d.get("hedge_symbol")
                events.append((
                    "tick",
                    {"ask": float(d["ask_diff"]), "bid": float(d["bid_diff"]),
                     "ts": d.get("ts"),
                     # absolute prices, used only to give simulated fills a
                     # realistic (positive) fill_price
                     "p_ask": float(d.get("primary_ask", 1.0)),
                     "p_bid": float(d.get("primary_bid", 1.0))},
                    wall,
                ))
                continue

            m = _SETTINGS_RE.search(line)
            if m:
                try:
                    parsed = ast.literal_eval(m.group(2))
                    wall = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f")
                    events.append(("settings", _to_raw_payload(parsed), wall))
                except (ValueError, SyntaxError, KeyError):
                    pass
                continue

            # ---- lines used only to reconstruct the *initial* state ----
            if initial_position is None:
                mp = _POSITION_RE.search(line)
                if mp:
                    initial_position = float(mp.group(1))

            if first_max_pos is None:
                # max_pos rides on the 'position=' line, logged before the Zone line.
                mm = _MAXPOS_RE.search(line)
                if mm:
                    first_max_pos = float(mm.group(1))

            if seen_order_size is None:
                mo = _PLACING_RE.search(line)
                if mo:
                    seen_order_size = float(mo.group(1))

            if initial_settings is None:
                mz = _ZONE_RE.search(line)
                if mz:
                    initial_settings = {
                        "long_upper": float(mz.group(1)),
                        "short_upper": float(mz.group(2)),
                        "short_lower": float(mz.group(3)),
                        "long_lower": float(mz.group(4)),
                        # max_pos / order_size aren't in the Zone line; fill in below.
                        "max_position_size": None,
                        "order_size": None,
                    }

    # Fill in the fields the Zone line can't provide: max_pos (from the first
    # 'position=' line) and order_size (first observed placing size, else CLI),
    # then convert to the raw Redis payload shape the bot parses.
    if initial_settings is not None:
        initial_settings["max_position_size"] = (
            first_max_pos if first_max_pos is not None else 0.0
        )
        initial_settings["order_size"] = (
            seen_order_size if seen_order_size is not None else default_order_size
        )
        initial_settings = _to_raw_payload(initial_settings)

    if initial_position is None:
        initial_position = 0.0

    return events, initial_settings, initial_position, primary, hedge


# ---------------------------------------------------------------------------
# Simulated log clock — stamps emitted log lines with the *original* event time
# (advanced by the replay loop) so the replay log shares the source timeline and
# plots.py charts overlay the original 1:1 instead of showing replay wall-clock.
# ---------------------------------------------------------------------------
_sim_clock = {"epoch": None, "msecs": 0.0}


def _set_sim_clock(dt):
    _sim_clock["epoch"] = dt.timestamp()
    _sim_clock["msecs"] = dt.microsecond / 1000.0


class _SimClockFilter(logging.Filter):
    def filter(self, record):
        if _sim_clock["epoch"] is not None:
            record.created = _sim_clock["epoch"]
            record.msecs = _sim_clock["msecs"]
            record.relativeCreated = 0
        return True


# ---------------------------------------------------------------------------
# Replay-output logging (isolated file in the production format)
# ---------------------------------------------------------------------------
def setup_replay_logging(out_path, quiet):
    """Route all `app.*` logs to out_path only, in the production verbose format."""
    fmt = logging.Formatter(
        "{levelname} {asctime} {name}:{funcName}:{lineno:d} "
        "PID:{process:d} {thread:d} {message}",
        style="{",
    )
    clock_filter = _SimClockFilter()

    fh = logging.FileHandler(out_path, mode="w", encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    fh.addFilter(clock_filter)

    handlers = [fh]
    if not quiet:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        ch.setLevel(logging.INFO)   # keep the terminal readable; file gets DEBUG
        ch.addFilter(clock_filter)
        handlers.append(ch)

    app_logger = logging.getLogger("app")
    app_logger.handlers = handlers          # replace the real quant.log handlers
    app_logger.setLevel(logging.DEBUG)
    app_logger.propagate = False

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Publishers
# ---------------------------------------------------------------------------
def publish_settings(r, key, raw_payload):
    payload = json.dumps(raw_payload)
    r.set(key, payload)        # initial fetch source for handle_grid_flow
    r.publish(key, payload)    # live update → grid_bot logs "Grid settings updated"


def publish_tick(r, key, primary, hedge, ask, bid, ts):
    payload = json.dumps({"ask_diff": ask, "bid_diff": bid, "ts": ts})
    # Emit the published-side markers plots.py looks for, then hand it to the bot.
    pub_log.debug(
        f"Price diff for {primary}/{hedge}: "
        f"{{'ask_diff': {ask}, 'bid_diff': {bid}, 'ts': {ts}}}"
    )
    pub_log.debug(f"Tick published upper={ask:+.2f} lower={bid:+.2f}")
    r.publish(key, payload)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def _resolve_pair_index(primary, hedge):
    for i, pair in enumerate(config.PAIRS):
        if pair["primary"]["symbol"] == primary and pair["hedge"]["symbol"] == hedge:
            return i
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Replay recorded ticks through the real grid bot (mocked fills).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("log", help="Input quant log file to replay")
    parser.add_argument("--output", "-o", metavar="FILE",
                        help="Replay log output path (default: <input dir>/replay_<stem>.log)")
    parser.add_argument("--interval", type=float, default=0.02,
                        help="Seconds between replayed ticks (default 0.02). In-memory "
                             "mocks are fast; keep >0 so each tick gets one decision.")
    parser.add_argument("--fill-pct", type=float, default=1.0,
                        help="Order fill fraction: 1.0=full, 0.5=partial, 0.0=none (default 1.0)")
    parser.add_argument("--position", type=float, default=None,
                        help="Override starting position (default: first 'position=' in the log)")
    parser.add_argument("--order-size", type=float, default=1.0,
                        help="Fallback initial order_size if none is recoverable from the log "
                             "(default 1.0). Overridden by any 'Grid settings updated' line.")
    parser.add_argument("--pair-index", type=int, default=None,
                        help="Force PAIR_INDEX instead of auto-detecting from the log")
    parser.add_argument("--quiet", action="store_true",
                        help="Don't echo INFO lines to the terminal (file still gets everything)")
    args = parser.parse_args()

    events, initial_settings, initial_position, primary, hedge = parse_log(
        args.log, args.order_size
    )

    n_ticks = sum(1 for e in events if e[0] == "tick")
    n_settings = sum(1 for e in events if e[0] == "settings")
    if n_ticks == 0:
        print("No 'price_diff:compare' ticks found in the log — nothing to replay.",
              file=sys.stderr)
        sys.exit(1)
    if primary is None:
        print("Could not determine the trading pair from the log.", file=sys.stderr)
        sys.exit(1)

    pair_index = args.pair_index
    if pair_index is None:
        pair_index = _resolve_pair_index(primary, hedge)
    if pair_index is None:
        print(f"Pair {primary}/{hedge} not found in config.PAIRS — pass --pair-index.",
              file=sys.stderr)
        sys.exit(1)
    os.environ["PAIR_INDEX"] = str(pair_index)

    if args.output:
        out_path = args.output
    else:
        # Embed the input log's name and the ATR params so the eventual
        # plots.py PNG (atr_<output-basename>.png) traces back to this source
        # log and each param variant lands in its own distinctly-named file.
        in_stem = os.path.splitext(os.path.basename(args.log))[0]
        tag = (f"atrP{grid_bot.ATR_PERIOD}-D{grid_bot.ATR_PERIOD_DOWN}"
               f"-t{grid_bot.ATR_HIGH_THRESHOLD}")
        out_path = os.path.join(os.path.dirname(os.path.abspath(args.log)),
                                f"replay_{in_stem}_{tag}.log")

    if args.position is not None:
        initial_position = args.position
    _market["position"] = initial_position
    _market["fill_pct"] = args.fill_pct

    # ---- summary to the terminal (before we hijack logging for the file) ----
    print("=== Grid Bot Replay ===")
    print(f"  Input       : {args.log}")
    print(f"  Output      : {out_path}")
    print(f"  Pair        : {primary}/{hedge}  (PAIR_INDEX={pair_index})")
    print(f"  Ticks       : {n_ticks}   settings changes: {n_settings}")
    print(f"  Start pos   : {initial_position}   fill_pct: {args.fill_pct}")
    print(f"  Init limits : {initial_settings}")
    print(f"  ATR params  : period={grid_bot.ATR_PERIOD} down={grid_bot.ATR_PERIOD_DOWN} "
          f"threshold={grid_bot.ATR_HIGH_THRESHOLD}")
    if initial_settings is None:
        print("  WARNING: no initial grid limits recoverable (no Zone= line before the "
              "first settings update) — the bot will block orders until the first "
              "'Grid settings updated' event.")

    # ---- wire up ----
    setup_replay_logging(out_path, args.quiet)
    r = _FakeRedis()
    patch_grid_bot(r)

    price_key = f"sim:price_diff:{primary}:{hedge}"
    grid_key = f"sim:setting_grid_channel:{primary}:{hedge}"

    pubsub = r.pubsub()
    pubsub.subscribe(price_key, grid_key)

    # Stamp startup lines at the first event's original time.
    _set_sim_clock(events[0][2])

    # Seed initial grid settings so handle_grid_flow's startup fetch succeeds.
    if initial_settings is not None:
        publish_settings(r, grid_key, initial_settings)

    threading.Thread(
        target=grid_bot.handle_grid_flow,
        args=(pubsub, price_key, grid_key, hedge),
        daemon=True,
    ).start()
    time.sleep(0.5)  # let the bot thread read initial settings

    # ---- replay the recorded stream ----
    t0 = time.time()
    for kind, data, wall in events:
        _set_sim_clock(wall)   # re-stamp emitted log lines onto the source timeline
        if kind == "settings":
            publish_settings(r, grid_key, data)
        else:
            # Update the market price the mock fills price against, then publish.
            _market["ask"], _market["bid"] = data["p_ask"], data["p_bid"]
            publish_tick(r, price_key, primary, hedge,
                         data["ask"], data["bid"], data["ts"])
        time.sleep(args.interval)

    time.sleep(1.0)  # flush any in-flight decision
    elapsed = time.time() - t0
    print(f"=== Done in {elapsed:.1f}s  (orders simulated: {_order_counter}, "
          f"final position: {_market['position']}) ===")
    print(f"Chart it:  python app/utils/plots.py --atr {out_path}")


if __name__ == "__main__":
    main()
