#!/usr/bin/env python3
"""
Grid bot simulation — runs the real handle_grid_flow with mocked Binance API.

All exchange calls (new_order, cancel, chase, get_open_orders, get_ticker,
get_position) are intercepted and logged.  No real orders are placed.

Usage (inside the django container, from /app):

  # Isolated mode (default) — uses sim: channels, safe alongside live bot
  PAIR_INDEX=1 python app/quant/algorithms/arbitrage/tests/simulate_bot.py --scenario sell_zone

  # Manual tick
  PAIR_INDEX=1 python ... --upper-diff 6.0 --lower-diff -2.0 --count 3

  # Live channels — ⚠️  only when live bot is stopped
  PAIR_INDEX=1 python ... --live-channels --scenario sweep

Scenarios: sell_zone | buy_zone | sweep | capacity_exceeded
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
    "bid": 3300.0,
    "ask": 3301.0,
    "position": 0.0,
    "open_orders": [],  # list of SimpleNamespace(side, price, orig_qty)
}

_order_counter = 0


# ---------------------------------------------------------------------------
# Mock interceptors
# ---------------------------------------------------------------------------

def mock_new_order(symbol, quantity, price, side):
    global _order_counter
    _order_counter += 1
    oid = f"SIM_{_order_counter:04d}"
    sim_log.info(f"  🟢 new_order  {side:4s}  qty={quantity}  price={price:.2f}  id={oid}")
    return SimpleNamespace(order_id=oid, status="NEW",
                           price=price, orig_qty=quantity, side=side)


def mock_cancel_all_open_orders(symbol):
    sim_log.info(f"  🔴 cancel_all_open_orders  {symbol}")
    _market["open_orders"].clear()
    return None


def mock_chase_order(symbol, quantity, side):
    sim_log.info(f"  🟡 chase_order  {side:4s}  qty={quantity}")
    return None


def mock_get_open_orders(symbol):
    return list(_market["open_orders"])


def mock_get_ticker(symbol):
    return {"best_bid": str(_market["bid"]), "best_ask": str(_market["ask"])}


def mock_get_position(symbol):
    return {"positionAmt": str(_market["position"])}


def mock_get_latest_order_snapshot(symbol):
    return {}


# ---------------------------------------------------------------------------
# Patch grid_bot module in-place
# ---------------------------------------------------------------------------

def patch_grid_bot():
    grid_bot.new_order = mock_new_order
    grid_bot.cancel_all_open_orders = mock_cancel_all_open_orders
    grid_bot.chase_order = mock_chase_order
    grid_bot.get_open_orders = mock_get_open_orders
    grid_bot.get_ticker = mock_get_ticker
    grid_bot.get_position = mock_get_position
    grid_bot.get_latest_order_snapshot = mock_get_latest_order_snapshot
    sim_log.info("Binance API patched — no real orders will be placed")


# ---------------------------------------------------------------------------
# Redis publishers
# ---------------------------------------------------------------------------

def publish_grid_settings(r, grid_range_key, upper_limit, lower_limit, max_pos, order_size):
    payload = json.dumps({
        "upper_diff": upper_limit,
        "lower_diff": lower_limit,
        "max_position_size": max_pos,
        "order_size": order_size,
    })
    r.set(grid_range_key, payload)       # initial fetch (bot reads on startup)
    r.publish(grid_range_key, payload)   # live update
    sim_log.info(
        f"Grid settings  upper={upper_limit}  lower={lower_limit}  "
        f"max_pos={max_pos}  order_size={order_size}"
    )


def publish_price_tick(r, price_diff_key, upper_diff, lower_diff, label=""):
    payload = json.dumps({
        "current_upper_diff": upper_diff,
        "current_lower_diff": lower_diff,
    })
    r.publish(price_diff_key, payload)
    tag = f"  [{label}]" if label else ""
    sim_log.debug(f"Tick published  upper={upper_diff:+.2f}  lower={lower_diff:+.2f}{tag}")


# ---------------------------------------------------------------------------
# Named scenarios  (upper_diff, lower_diff, label)
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, list[tuple]] = {
    "sell_zone": [
        (2.0,  2.0,  "within range"),
        (6.0,  2.0,  "SELL zone — expects new SELL order"),
        (6.0,  2.0,  "SELL zone again — expects chase or no-op"),
        (2.0,  2.0,  "back to range"),
    ],
    "buy_zone": [
        (2.0,  -2.0, "within range"),
        (2.0,  -6.0, "BUY zone — expects new BUY order"),
        (2.0,  -6.0, "BUY zone again — expects chase or no-op"),
        (2.0,  -2.0, "back to range"),
    ],
    "sweep": [
        (2.0,  -2.0, "neutral"),
        (6.0,  -2.0, "sell zone"),
        (2.0,  -2.0, "neutral"),
        (2.0,  -6.0, "buy zone"),
        (2.0,  -2.0, "neutral"),
        (9.0,   2.0, "deep sell zone"),
        (2.0,  -9.0, "deep buy zone"),
        (2.0,  -2.0, "back to neutral"),
    ],
    "capacity_exceeded": [
        (2.0,  -2.0, "neutral — set position to max before running"),
        (6.0,  -2.0, "sell zone but capacity full — expects cancel"),
        (2.0,  -6.0, "buy zone but capacity full — expects cancel"),
    ],
}


def run_scenario(r, price_diff_key, name, interval, repeat):
    steps = SCENARIOS.get(name)
    if not steps:
        sim_log.error(f"Unknown scenario '{name}'. Choose from: {list(SCENARIOS)}")
        return
    for run in range(repeat):
        sim_log.info(f"--- Scenario '{name}'  run {run + 1}/{repeat} ---")
        for upper, lower, label in steps:
            sim_log.info(f"  Step: {label}")
            publish_price_tick(r, price_diff_key, upper, lower, label)
            time.sleep(interval)


def run_manual(r, price_diff_key, upper_diff, lower_diff, interval, count):
    sim_log.info(f"Manual ticks x{count}  upper={upper_diff:+.2f}  lower={lower_diff:+.2f}")
    for i in range(count):
        publish_price_tick(r, price_diff_key, upper_diff, lower_diff, f"{i+1}/{count}")
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
                       help="Manual mode: current_upper_diff to publish (default 6.0)")
    parser.add_argument("--lower-diff", type=float, default=-6.0,
                        help="Manual mode: current_lower_diff to publish (default -6.0)")
    parser.add_argument("--count", type=int, default=5,
                        help="Number of ticks in manual mode (default 5)")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="Seconds between ticks (default 1.0)")
    parser.add_argument("--repeat", type=int, default=1,
                        help="Times to repeat a named scenario (default 1)")

    # market state
    parser.add_argument("--bid", type=float, default=3300.0)
    parser.add_argument("--ask", type=float, default=3301.0)
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
    sim_log.info(f"  Grid limits : upper={args.upper_limit}  lower={args.lower_limit}")

    # ---- print incoming parameters ----
    sim_log.info("--- Parameters ---")
    sim_log.info(f"  scenario    : {args.scenario}")
    sim_log.info(f"  upper_diff  : {args.upper_diff}")
    sim_log.info(f"  lower_diff  : {args.lower_diff}")
    sim_log.info(f"  count       : {args.count}")
    sim_log.info(f"  interval    : {args.interval}")
    sim_log.info(f"  repeat      : {args.repeat}")
    sim_log.info(f"  bid         : {args.bid}")
    sim_log.info(f"  ask         : {args.ask}")
    sim_log.info(f"  position    : {args.position}")
    sim_log.info(f"  upper_limit : {args.upper_limit}")
    sim_log.info(f"  lower_limit : {args.lower_limit}")
    sim_log.info(f"  max_pos     : {args.max_pos}")
    sim_log.info(f"  order_size  : {args.order_size}")
    sim_log.info(f"  live_channels: {args.live_channels}")

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
    sim_log.info("")

    if args.scenario:
        run_scenario(redis_conn, price_diff_key, args.scenario, args.interval, args.repeat)
    else:
        run_manual(redis_conn, price_diff_key, args.upper_diff, args.lower_diff,
                   args.interval, args.count)

    time.sleep(1.0)  # flush any in-flight messages
    sim_log.info("")
    sim_log.info(f"=== Done  (orders intercepted: {_order_counter}) ===")


if __name__ == "__main__":
    main()
