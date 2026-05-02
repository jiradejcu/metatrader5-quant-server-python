#!/usr/bin/env python3
"""
Grid bot simulation — runs the real handle_grid_flow with mocked Binance API.

All exchange calls (cancel, chase_order, get_open_orders,
get_position) are intercepted and logged.  No real orders are placed.

Usage (inside the django container, from /app):

  # Isolated mode (default) — uses sim: channels, safe alongside live bot
  PAIR_INDEX=1 python app/quant/algorithms/arbitrage/tests/simulate_bot.py --scenario sell_zone

  # Manual tick
  PAIR_INDEX=1 python ... --upper-diff 6.0 --lower-diff -2.0 --count 3

  # Live channels — ⚠️  only when live bot is stopped
  PAIR_INDEX=1 python ... --live-channels --scenario sweep

Scenarios: sell_accumulate, complete
"""

import os
import sys
import json
import time
import logging
import argparse
import threading
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# Django setup (must happen before any app.* import)
# ---------------------------------------------------------------------------

# When run as a script, Python sets sys.path[0] to the script directory.
# Insert the project root (/app) so "import app.*" resolves correctly.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../../"))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
import django
django.setup()

import app.quant.algorithms.arbitrage.grid_bot as grid_bot
import app.quant.algorithms.arbitrage.config as config
from app.utils.redis_client import get_redis_connection

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
sim_log = logging.getLogger(
    os.path.splitext(os.path.relpath(__file__, _PROJECT_ROOT))[0].replace(os.sep, ".")
)

# Quieten noisy background loggers
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Mutable market state — set from CLI args before starting threads
# ---------------------------------------------------------------------------
_market = {
    "bid": 1000.0,
    "ask": 1001.0,
    "position": 0.0,
    "open_orders": [],   # list of SimpleNamespace(order_id, side, orig_qty)
    "last_snapshot": {}, # latest order snapshot returned to the poller
    "fill_pct": 1.0,     # 0.0 = no fill, 0.5 = partial, 1.0 = full (default)
}

_order_counter = 0


# ---------------------------------------------------------------------------
# Mock interceptors
# ---------------------------------------------------------------------------

def mock_cancel_all_open_orders(symbol):
    sim_log.info(f"  🔴 cancel_all_open_orders  {symbol}")
    if _market["open_orders"]:
        _market["last_snapshot"] = {**_market["last_snapshot"], "status": "CANCELED"}
    _market["open_orders"].clear()
    return None


def mock_chase_order(symbol, quantity, side):
    global _order_counter

    if _market["open_orders"]:
        # Existing open order — update to current OPPONENT price (best market price)
        order = _market["open_orders"][0]
        sim_log.info(
            f"  🟡 chase_order  {side:4s}  qty={quantity}  id={order.order_id}  "
            f"(OPPONENT: bid={_market['bid']}  ask={_market['ask']})"
        )
        return SimpleNamespace(order_id=order.order_id)

    # No open order — place new via OPPONENT price match
    _order_counter += 1
    oid = f"SIM_{_order_counter:04d}"
    fill_pct = _market["fill_pct"]
    filled_qty = round(quantity * fill_pct, 8)
    remaining_qty = round(quantity - filled_qty, 8)

    delta = filled_qty if side == 'BUY' else -filled_qty
    _market["position"] = round(_market["position"] + delta, 8)

    if remaining_qty > 0:
        status = "PARTIALLY_FILLED" if fill_pct > 0 else "NEW"
        order = SimpleNamespace(order_id=oid, side=side, orig_qty=remaining_qty)
        _market["open_orders"].append(order)
        _market["last_snapshot"] = {
            "order_id": oid, "status": status, "side": side,
            "orig_qty": quantity, "fill_pct": fill_pct * 100, "is_clean": True,
        }
        sim_log.info(
            f"  🟢 chase_order (new)  {side:4s}  qty={quantity}  id={oid}  "
            f"fill={fill_pct*100:.0f}%  remaining={remaining_qty}  position={_market['position']:+.4f}"
        )
    else:
        status = "FILLED"
        _market["last_snapshot"] = {
            "order_id": oid, "status": "FILLED", "side": side,
            "orig_qty": quantity, "fill_pct": 100, "is_clean": True,
        }
        sim_log.info(f"  🟢 chase_order (new)  {side:4s}  qty={quantity}  id={oid}")
        sim_log.info(f"  💰 filled             {side:4s}  qty={quantity}  position={_market['position']:+.4f}")

    return SimpleNamespace(order_id=oid, status=status, orig_qty=quantity, side=side)


def mock_get_open_orders(symbol):
    return list(_market["open_orders"])


def mock_get_position(symbol):
    return {"positionAmt": str(_market["position"])}


def mock_get_latest_order_snapshot(symbol):
    # Clear last_acted_order_id once the poller reads the snapshot so the stale
    # guard releases and subsequent ticks (e.g. chase) are not blocked.
    grid_bot.last_acted_order_id = None
    return _market["last_snapshot"]


# ---------------------------------------------------------------------------
# Patch grid_bot module in-place
# ---------------------------------------------------------------------------

def patch_grid_bot():
    grid_bot.cancel_all_open_orders = mock_cancel_all_open_orders
    grid_bot.chase_order = mock_chase_order
    grid_bot.get_open_orders = mock_get_open_orders
    grid_bot.get_position = mock_get_position
    grid_bot.get_latest_order_snapshot = mock_get_latest_order_snapshot
    sim_log.info("Binance API patched — no real orders will be placed")


# ---------------------------------------------------------------------------
# Redis publishers
# ---------------------------------------------------------------------------

def publish_grid_settings(r, grid_range_key, upper_limit, lower_limit, max_pos, order_size):
    payload = json.dumps({
        "upper_limit": upper_limit,
        "lower_limit": lower_limit,
        "max_position_size": max_pos,
        "order_size": order_size,
    })
    r.set(grid_range_key, payload)       # initial fetch (bot reads on startup)
    r.publish(grid_range_key, payload)   # live update
    sim_log.info(
        f"Grid settings  upper={upper_limit}  lower={lower_limit}  "
        f"max_pos={max_pos}  order_size={order_size}"
    )


def publish_price_tick(r, price_diff_key, upper_limit, lower_limit, label=""):
    payload = json.dumps({
        "ask_diff": upper_limit,
        "bid_diff": lower_limit,
    })
    r.publish(price_diff_key, payload)
    tag = f"  [{label}]" if label else ""
    sim_log.debug(f"Tick published  upper={upper_limit:+.2f}  lower={lower_limit:+.2f}{tag}")


# ---------------------------------------------------------------------------
# Named scenarios
#
# Each step is a tuple: (upper_limit, lower_limit, label, bid, ask, fill_pct)
#   bid, ask, fill_pct are optional; omit trailing fields to keep current values.
#
# fill_pct: 0.0=no fill, 0.5=partial, 1.0=full fill
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, list[tuple]] = {
    # Run with: --scenario sell_accumulate --max-pos 3 --order-size 1
    #
    # Shows the bot accumulating a short position one order at a time in the
    # SELL zone until max_position_size is reached, then holding.
    #
    # Expected position after each fill:  0 → -1 → -2 → -3 (capped)
    "sell_accumulate": [
        # start flat in NEUTRAL — target=pos(0), no open order → nothing to do
        (2.0, -2.0, "neutral  pos=0 → no action",          1000.0, 1001.0, 1.0),

        # SELL zone — target = 0-1 = -1, place+fill SELL 1 → pos=-1
        (6.0, -2.0, "SELL  pos=0  cap=3 → place+fill #1",  1000.0, 1001.0, 1.0),

        # still SELL — target = -1-1 = -2, place+fill SELL 1 → pos=-2
        (6.0, -2.0, "SELL  pos=-1 cap=2 → place+fill #2",  1000.0, 1001.0, 1.0),

        # still SELL — target = -2-1 = -3, place+fill SELL 1 → pos=-3
        (6.0, -2.0, "SELL  pos=-2 cap=1 → place+fill #3",  1000.0, 1001.0, 1.0),

        # still SELL — cap=0, target=pos(-3) → no open order, nothing to cancel
        (6.0, -2.0, "SELL  pos=-3 cap=0 → capacity hit, no action", 1000.0, 1001.0, 1.0),

        # back to NEUTRAL — target=pos(-3) → cancel open orders (none open)
        (2.0, -2.0, "neutral pos=-3 → no action",          1000.0, 1001.0, 1.0),
    ],

    "complete": [
        # --- Phase 1: SELL zone, no fill — ask drops, must chase SELL down ---
        (2.0, -2.0, "neutral  pos=0 → no action",               1000.0, 1001.0, 0.0),
        (6.0, -2.0, "SELL  pos=0 → place(no fill)",             1000.0, 1001.0, 0.0),
        (6.0, -2.0, "SELL  pos=0 → chase(ask↓1000)",             999.0, 1000.0, 0.0),
        (6.0, -2.0, "SELL  pos=0 → chase(ask↓999)",              998.0,  999.0, 0.0),
        (2.0, -2.0, "→neutral  pos=0 → cancel open",            1000.0, 1001.0, 0.0),

        # --- Phase 2: SELL zone, partial fill — remaining qty chased ---
        (6.0, -2.0, "SELL  pos=0 → place(50% fill)",            1000.0, 1001.0, 0.5),
        (6.0, -2.0, "SELL  pos=-0.5 → chase remaining(ask↓)",    999.0, 1000.0, 0.5),
        (2.0, -2.0, "→neutral  pos=-0.5 → cancel open",         1000.0, 1001.0, 0.5),

        # --- Phase 3: SELL zone, partial fill → then fully filled on next tick ---
        (6.0, -2.0, "SELL  pos=-0.5 → place(50% fill)",         1000.0, 1001.0, 0.5),
        (6.0, -2.0, "SELL  pos=-1.0 → chase→full fill",          999.0, 1000.0, 1.0),
        (2.0, -2.0, "→neutral  pos=-1.5 → no open order",       1000.0, 1001.0, 1.0),

        # --- Phase 4: SELL zone, full fill → neutral holds position ---
        (6.0, -2.0, "SELL  pos=-1.5 → place+fill",              1000.0, 1001.0, 1.0),
        (2.0, -2.0, "→neutral  pos=-2.5 → no open order",       1000.0, 1001.0, 1.0),

        # --- Phase 5: BUY zone, full fill → neutral holds position ---
        (2.0, -6.0, "BUY   pos=-2.5 → place+fill",              1000.0, 1001.0, 1.0),
        (2.0, -2.0, "→neutral  pos=-1.5 → no open order",       1000.0, 1001.0, 1.0),
    ],
}


def run_scenario(r, price_diff_key, name, interval, repeat):
    steps = SCENARIOS.get(name)
    if not steps:
        sim_log.error(f"Unknown scenario '{name}'. Choose from: {list(SCENARIOS)}")
        return
    for run in range(repeat):
        sim_log.info(f"--- Scenario '{name}'  run {run + 1}/{repeat} ---")
        for step in steps:
            upper, lower, label = step[0], step[1], step[2]
            if len(step) >= 5:
                _market["bid"], _market["ask"] = step[3], step[4]
            if len(step) >= 6:
                _market["fill_pct"] = step[5]
            sim_log.info(
                f"  [{label}]  upper={upper:+.1f}  lower={lower:+.1f}  "
                f"bid={_market['bid']}  ask={_market['ask']}  fill={_market['fill_pct']:.0%}"
            )
            publish_price_tick(r, price_diff_key, upper, lower, label)
            time.sleep(interval)


def run_manual(r, price_diff_key, upper_limit, lower_limit, interval, count):
    sim_log.info(f"Manual ticks x{count}  upper={upper_limit:+.2f}  lower={lower_limit:+.2f}")
    for i in range(count):
        publish_price_tick(r, price_diff_key, upper_limit, lower_limit, f"{i+1}/{count}")
        time.sleep(interval)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Simulate the grid bot with mocked Binance API calls",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # scenario / manual
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--scenario", choices=list(SCENARIOS),
                       help="Run a named price scenario")
    group.add_argument("--upper-diff", type=float, default=6.0,
                       help="Manual mode: current_upper_limit to publish (default 6.0)")
    parser.add_argument("--lower-diff", type=float, default=-6.0,
                        help="Manual mode: current_lower_limit to publish (default -6.0)")
    parser.add_argument("--count", type=int, default=5,
                        help="Number of ticks in manual mode (default 5)")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="Seconds between ticks (default 1.0)")
    parser.add_argument("--repeat", type=int, default=1,
                        help="Times to repeat a named scenario (default 1)")

    # market state
    parser.add_argument("--bid", type=float, default=1000.0)
    parser.add_argument("--ask", type=float, default=1001.0)
    parser.add_argument("--position", type=float, default=0.0,
                        help="Simulated open position (default 0)")

    # grid settings
    parser.add_argument("--upper-limit", type=float, default=5.0,
                        help="Grid upper threshold stored in Redis (default 5.0)")
    parser.add_argument("--lower-limit", type=float, default=-5.0,
                        help="Grid lower threshold stored in Redis (default -5.0)")
    parser.add_argument("--max-pos", type=float, default=5.0)
    parser.add_argument("--order-size", type=float, default=1.0)

    # channel mode
    parser.add_argument(
        "--live-channels", action="store_true",
        help=(
            "⚠️  Use the real production Redis channels. "
            "Only safe when the live bot is stopped."
        ),
    )

    args = parser.parse_args()

    # ---- resolve pair config ----
    pair_index = int(os.getenv("PAIR_INDEX", "1"))
    pair = config.PAIRS[pair_index]
    exchange = pair["entry"]["exchange"]
    entry_symbol = pair["entry"]["symbol"]
    hedge_symbol = pair["hedge"]["symbol"]

    if args.live_channels:
        price_diff_key = f"spread:{exchange}:{entry_symbol}"
        grid_range_key = f"setting_grid_channel:{entry_symbol}:{hedge_symbol}"
        sim_log.warning("⚠️  LIVE CHANNELS — messages will reach the running bot too")
    else:
        price_diff_key = f"sim:spread:{exchange}:{entry_symbol}"
        grid_range_key = f"sim:setting_grid_channel:{entry_symbol}:{hedge_symbol}"

    # ---- update market state ----
    _market["bid"] = args.bid
    _market["ask"] = args.ask
    _market["position"] = args.position

    sim_log.info("=== Grid Bot Simulation ===")
    sim_log.info(f"  Pair        : {entry_symbol}  (PAIR_INDEX={pair_index})")
    sim_log.info(f"  Price ch    : {price_diff_key}")
    sim_log.info(f"  Settings ch : {grid_range_key}")
    sim_log.info(f"  Market      : bid={args.bid}  ask={args.ask}  position={args.position}")
    sim_log.info(f"  Grid limits : upper={args.upper_limit}  lower={args.lower_limit}  max_pos={args.max_pos}  order_size={args.order_size}")
    sim_log.info(f"  Live ch     : {args.live_channels}")
    if args.scenario:
        sim_log.info(f"  Mode        : scenario={args.scenario}  repeat={args.repeat}  interval={args.interval}s")
    else:
        sim_log.info(f"  Mode        : manual  upper_diff={args.upper_diff}  lower_diff={args.lower_diff}  count={args.count}  interval={args.interval}s")

    # ---- patch + start bot ----
    patch_grid_bot()

    redis_conn = get_redis_connection()
    pubsub = redis_conn.pubsub()
    pubsub.subscribe(price_diff_key, grid_range_key)

    publish_grid_settings(
        redis_conn, grid_range_key,
        args.upper_limit, args.lower_limit, args.max_pos, args.order_size,
    )

    threading.Thread(
        target=grid_bot.handle_grid_flow,
        args=(pubsub, price_diff_key, grid_range_key),
        daemon=True,
    ).start()
    threading.Thread(
        target=grid_bot.poll_order_state,
        args=(entry_symbol,),
        daemon=True,
    ).start()

    time.sleep(0.5)  # let threads initialize and read initial settings
    sim_log.info("Bot threads started. Publishing price data...")

    if args.scenario:
        run_scenario(redis_conn, price_diff_key, args.scenario, args.interval, args.repeat)
    else:
        run_manual(redis_conn, price_diff_key, args.upper_diff, args.lower_diff,
                   args.interval, args.count)

    time.sleep(1.0)  # flush any in-flight messages
    sim_log.info(f"=== Done  (orders intercepted: {_order_counter}) ===")


if __name__ == "__main__":
    main()
