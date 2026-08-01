#!/usr/bin/env python3
"""
Prediction bot simulation — runs the real handle_prediction_flow with mocked
Binance API and gating.

All exchange calls (chase_order, close_order, cancel_all_open_orders,
get_position, get_ticker, get_order_book, get_open_orders) are intercepted
and logged. No real orders are placed. Gating (enable flag, trading-session
window, computed-active heartbeat) is patched out so the sim never reads or
writes the live control keys — only the settings channel is real Redis
pubsub, and it defaults to a sim: prefix.

Usage (inside the django container, from /app):

  # Isolated mode (default) — uses sim: settings channel
  PAIR_INDEX=1 python app/quant/algorithms/prediction/tests/simulate_bot.py --scenario passive_close

  # Manual tick
  PAIR_INDEX=1 python ... --bid 1050 --ask 1051 --position 2 --entry-price 1000 --count 3

  # Live settings channel — reads/writes the real prediction settings key
  PAIR_INDEX=1 python ... --live-channels --scenario reentry

Scenarios: neutral_hold, passive_close, aggressive_close_slippage_capped,
reentry_after_close, cancel_on_target_lost
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

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../../"))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
import django
django.setup()

import app.quant.algorithms.prediction.prediction_bot as prediction_bot
import app.quant.algorithms.arbitrage.config as config
from app.utils.redis_client import get_redis_connection

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
sim_log = logging.getLogger(
    os.path.splitext(os.path.relpath(__file__, _PROJECT_ROOT))[0].replace(os.sep, ".")
)

logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Mutable market state — set from CLI args before starting threads
# ---------------------------------------------------------------------------
_market = {
    "bid": 1000.0,
    "ask": 1001.0,
    "position": 0.0,
    "entry_price": 0.0,
    "open_orders": [],   # list of SimpleNamespace(order_id, side, orig_qty)
    "bids": [(1000.0, 5.0), (999.0, 5.0), (998.0, 5.0), (997.0, 5.0)],
    "fill_pct": 1.0,     # 0.0 = no fill, 0.5 = partial, 1.0 = full (default)
}

_order_counter = 0


# ---------------------------------------------------------------------------
# Mock interceptors
# ---------------------------------------------------------------------------

def mock_get_position(symbol, force=False):
    return {
        "positionAmt": str(_market["position"]),
        "entryPrice": str(_market["entry_price"]),
    }


def mock_get_ticker(symbol):
    return {"best_bid": _market["bid"], "best_ask": _market["ask"], "event_ts": time.time()}


def mock_get_order_book(symbol, limit=50):
    return {"bids": list(_market["bids"]), "asks": [(_market["ask"], 5.0)]}


def mock_get_open_orders(symbol):
    return list(_market["open_orders"])


def mock_cancel_all_open_orders(symbol):
    sim_log.info(f"  🔴 cancel_all_open_orders  {symbol}")
    _market["open_orders"].clear()
    return None


def mock_chase_order(symbol, quantity, side, order_id=None):
    global _order_counter

    if order_id is not None:
        sim_log.info(
            f"  🟡 chase_order  {side:4s}  qty={quantity}  id={order_id}  "
            f"bid={_market['bid']}  ask={_market['ask']}"
        )
        return SimpleNamespace(order_id=order_id)

    _order_counter += 1
    oid = f"SIM_{_order_counter:04d}"
    fill_pct = _market["fill_pct"]
    filled_qty = round(quantity * fill_pct, 8)
    remaining_qty = round(quantity - filled_qty, 8)

    delta = filled_qty if side == 'BUY' else -filled_qty
    _market["position"] = round(_market["position"] + delta, 8)
    if side == 'BUY' and filled_qty > 0 and not _market["entry_price"]:
        _market["entry_price"] = _market["ask"]

    if remaining_qty > 0:
        order = SimpleNamespace(order_id=oid, side=side, orig_qty=remaining_qty)
        _market["open_orders"].append(order)
        sim_log.info(
            f"  🟢 chase_order (new)  {side:4s}  qty={quantity}  id={oid}  "
            f"fill={fill_pct*100:.0f}%  remaining={remaining_qty}  position={_market['position']:+.4f}"
        )
    else:
        sim_log.info(f"  🟢 chase_order (new)  {side:4s}  qty={quantity}  id={oid}")
        sim_log.info(f"  💰 filled             {side:4s}  qty={quantity}  position={_market['position']:+.4f}")

    return SimpleNamespace(order_id=oid, side=side, orig_qty=quantity)


def mock_close_order(symbol, quantity, side, price):
    """Reduce-only IOC — always fully fills the requested (already
    slippage-capped) quantity, same as _close_aggressive expects."""
    delta = -quantity if side == 'SELL' else quantity
    _market["position"] = round(_market["position"] + delta, 8)
    if _market["position"] <= 0:
        _market["entry_price"] = 0.0
    sim_log.info(
        f"  💥 close_order (aggressive)  {side:4s}  qty={quantity}  price={price}  "
        f"position={_market['position']:+.4f}"
    )
    return SimpleNamespace(order_id=f"SIM_CLOSE_{_order_counter}", side=side, orig_qty=quantity)


def mock_get_enable_status():
    return "1"


def mock_is_within_trading_session(primary_symbol, hedge_symbol):
    return False  # sim always runs "outside session" — prediction_bot's own gate


def mock_set_computed_active(is_active):
    pass  # skip writing the live heartbeat/status key


# ---------------------------------------------------------------------------
# Patch prediction_bot module in-place
# ---------------------------------------------------------------------------

def patch_prediction_bot():
    prediction_bot.get_position = mock_get_position
    prediction_bot.get_ticker = mock_get_ticker
    prediction_bot.get_order_book = mock_get_order_book
    prediction_bot.get_open_orders = mock_get_open_orders
    prediction_bot.cancel_all_open_orders = mock_cancel_all_open_orders
    prediction_bot.chase_order = mock_chase_order
    prediction_bot.close_order = mock_close_order
    prediction_bot.get_enable_status = mock_get_enable_status
    prediction_bot.is_within_trading_session = mock_is_within_trading_session
    prediction_bot._set_computed_active = mock_set_computed_active
    sim_log.info("Binance API + gating patched — no real orders or live control keys touched")


# ---------------------------------------------------------------------------
# Redis publishers
# ---------------------------------------------------------------------------

def publish_prediction_settings(r, settings_channel, settings):
    payload = json.dumps(settings)
    r.set(settings_channel, payload)      # initial fetch (bot reads on startup)
    r.publish(settings_channel, payload)  # live update
    sim_log.info(f"Settings  {settings}")


# ---------------------------------------------------------------------------
# Named scenarios
#
# Each step is a dict of _market field overrides plus a "label". Fields
# omitted keep their current value. The real handle_prediction_flow thread
# polls _process_tick every `interval` seconds and reacts to whatever
# _market currently holds.
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, list[dict]] = {
    # Run with: --scenario neutral_hold --profit-target 10 --reentry-tolerance 3
    #
    # Holding a position with profit below target — bot should do nothing.
    "neutral_hold": [
        {"label": "open long  pos=2 @1000",              "position": 2.0, "entry_price": 1000.0, "bid": 1004.0, "ask": 1005.0},
        {"label": "still below target (profit=4<10)",    "bid": 1004.0, "ask": 1005.0},
    ],

    # Run with: --scenario passive_close --profit-target 10 --aggressiveness passive
    #
    # Price runs up past profit_target_usd → bot places a passive best-ask
    # SELL, fully fills next tick (fill_pct=1.0 default).
    "passive_close": [
        {"label": "open long  pos=2 @1000",               "position": 2.0, "entry_price": 1000.0, "bid": 1005.0, "ask": 1006.0},
        {"label": "target met (profit=12>=10) → place SELL", "bid": 1012.0, "ask": 1013.0},
        {"label": "closed → flat, no action",              "bid": 1012.0, "ask": 1013.0},
    ],

    # Run with: --scenario aggressive_close_slippage_capped --profit-target 5
    #            --max-slippage 3 --aggressiveness aggressive --position 5
    #
    # Book only has enough depth within max_slippage_usd to close part of the
    # position — bot should close the closeable qty, leaving the remainder
    # open for the next tick.
    "aggressive_close_slippage_capped": [
        {
            "label": "open long pos=5 @1000, target met → partial aggressive close",
            "position": 5.0, "entry_price": 1000.0,
            "bid": 1010.0, "ask": 1011.0,
            "bids": [(1010.0, 2.0), (1008.0, 2.0), (1005.0, 2.0)],
        },
        {"label": "remaining position → close again next tick", "bid": 1010.0, "ask": 1011.0},
    ],

    # Run with: --scenario reentry_after_close --profit-target 10 --reentry-tolerance 3
    #
    # After a full close, price gives back the run-up to within
    # reentry_tolerance_usd of the original entry → bot buys back.
    "reentry_after_close": [
        {"label": "open long pos=2 @1000",                 "position": 2.0, "entry_price": 1000.0, "bid": 1005.0, "ask": 1006.0},
        {"label": "target met (profit=12>=10) → SELL",     "bid": 1012.0, "ask": 1013.0},
        {"label": "flat, price still elevated → wait",     "bid": 1006.0, "ask": 1007.0},
        {"label": "price back near entry+tolerance → BUY back", "bid": 999.0, "ask": 1001.0},
    ],

    # Run with: --scenario cancel_on_target_lost --profit-target 10
    #
    # A resting passive close order exists, but price drops back below
    # target before it fills → bot should cancel it.
    "cancel_on_target_lost": [
        {"label": "open long pos=2 @1000, target met, no fill → place SELL",
         "position": 2.0, "entry_price": 1000.0, "bid": 1012.0, "ask": 1013.0, "fill_pct": 0.0},
        {"label": "price drops back below target → cancel SELL",
         "bid": 1004.0, "ask": 1005.0},
    ],
}


def run_scenario(r, settings_channel, name, interval, repeat, settings):
    steps = SCENARIOS.get(name)
    if not steps:
        sim_log.error(f"Unknown scenario '{name}'. Choose from: {list(SCENARIOS)}")
        return
    for run in range(repeat):
        sim_log.info(f"--- Scenario '{name}'  run {run + 1}/{repeat} ---")
        for step in steps:
            label = step.get("label", "")
            for key in ("bid", "ask", "position", "entry_price", "bids", "fill_pct"):
                if key in step:
                    _market[key] = step[key]
            sim_log.info(
                f"  [{label}]  bid={_market['bid']}  ask={_market['ask']}  "
                f"position={_market['position']:+.4f}  entry_price={_market['entry_price']}"
            )
            time.sleep(interval)


def run_manual(r, interval, count, bid_step, ask_step):
    sim_log.info(f"Manual ticks x{count}  bid_step={bid_step}  ask_step={ask_step}")
    for i in range(count):
        _market["bid"] += bid_step
        _market["ask"] += ask_step
        sim_log.info(
            f"  [{i+1}/{count}]  bid={_market['bid']:.2f}  ask={_market['ask']:.2f}  "
            f"position={_market['position']:+.4f}"
        )
        time.sleep(interval)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Simulate the prediction bot with mocked Binance API + gating",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--scenario", choices=list(SCENARIOS),
                       help="Run a named price scenario")
    parser.add_argument("--bid-step", type=float, default=1.0,
                        help="Manual mode: bid change per tick (default 1.0)")
    parser.add_argument("--ask-step", type=float, default=1.0,
                        help="Manual mode: ask change per tick (default 1.0)")
    parser.add_argument("--count", type=int, default=5,
                        help="Number of ticks in manual mode (default 5)")
    parser.add_argument("--interval", type=float, default=2.5,
                        help="Seconds between ticks; must exceed poll_interval (default 2.5)")
    parser.add_argument("--poll-interval", type=float, default=1.0,
                        help="Bot poll_interval passed to handle_prediction_flow (default 1.0)")
    parser.add_argument("--repeat", type=int, default=1,
                        help="Times to repeat a named scenario (default 1)")

    parser.add_argument("--bid", type=float, default=1000.0)
    parser.add_argument("--ask", type=float, default=1001.0)
    parser.add_argument("--position", type=float, default=0.0)
    parser.add_argument("--entry-price", type=float, default=0.0)

    parser.add_argument("--profit-target", type=float, default=10.0)
    parser.add_argument("--max-slippage", type=float, default=5.0)
    parser.add_argument("--aggressiveness", choices=["passive", "aggressive"], default="passive")
    parser.add_argument("--reentry-tolerance", type=float, default=3.0)
    parser.add_argument("--max-close-size", type=float, default=0.0)
    parser.add_argument("--force-aggressive-minutes", type=float, default=0.0)

    parser.add_argument(
        "--live-channels", action="store_true",
        help="⚠️  Use the real production prediction settings channel.",
    )

    args = parser.parse_args()

    pair_index = int(os.getenv("PAIR_INDEX", "1"))
    pair = config.PAIRS[pair_index]
    primary_symbol = pair["primary"]["symbol"]
    hedge_symbol = pair["hedge"]["symbol"]

    if args.live_channels:
        settings_channel = f"setting_prediction_channel:{primary_symbol}:{hedge_symbol}"
        sim_log.warning("⚠️  LIVE SETTINGS CHANNEL — will overwrite the real prediction settings")
    else:
        settings_channel = f"sim:setting_prediction_channel:{primary_symbol}:{hedge_symbol}"

    _market["bid"] = args.bid
    _market["ask"] = args.ask
    _market["position"] = args.position
    _market["entry_price"] = args.entry_price

    settings = {
        "profit_target_usd": args.profit_target,
        "max_slippage_usd": args.max_slippage,
        "aggressiveness": args.aggressiveness,
        "reentry_tolerance_usd": args.reentry_tolerance,
        "max_close_size": args.max_close_size,
        "force_aggressive_minutes_before_reopen": args.force_aggressive_minutes,
    }

    sim_log.info("=== Prediction Bot Simulation ===")
    sim_log.info(f"  Pair        : {primary_symbol}  (PAIR_INDEX={pair_index})")
    sim_log.info(f"  Settings ch : {settings_channel}")
    sim_log.info(f"  Market      : bid={args.bid}  ask={args.ask}  position={args.position}  entry_price={args.entry_price}")
    sim_log.info(f"  Settings    : {settings}")
    if args.scenario:
        sim_log.info(f"  Mode        : scenario={args.scenario}  repeat={args.repeat}  interval={args.interval}s")
    else:
        sim_log.info(f"  Mode        : manual  bid_step={args.bid_step}  ask_step={args.ask_step}  count={args.count}  interval={args.interval}s")

    patch_prediction_bot()

    redis_conn = get_redis_connection()
    pubsub = redis_conn.pubsub()
    pubsub.subscribe(settings_channel)

    publish_prediction_settings(redis_conn, settings_channel, settings)

    threading.Thread(
        target=prediction_bot.handle_prediction_flow,
        args=(pubsub, settings_channel, primary_symbol, hedge_symbol),
        kwargs={"poll_interval": args.poll_interval},
        daemon=True,
    ).start()

    time.sleep(0.5)  # let threads initialize and read initial settings
    sim_log.info("Bot thread started. Driving synthetic price ticks...")

    if args.scenario:
        run_scenario(redis_conn, settings_channel, args.scenario, args.interval, args.repeat, settings)
    else:
        run_manual(redis_conn, args.interval, args.count, args.bid_step, args.ask_step)

    time.sleep(args.poll_interval + 0.5)  # flush any in-flight tick
    sim_log.info(f"=== Done  (orders intercepted: {_order_counter}) ===")


if __name__ == "__main__":
    main()
