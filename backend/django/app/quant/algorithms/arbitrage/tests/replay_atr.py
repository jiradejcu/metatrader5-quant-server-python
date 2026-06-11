#!/usr/bin/env python3
"""
Parse price_diff log lines and replay them through the ATR guard so you can
tune ATR_PERIOD and ATR_HIGH_THRESHOLD without running the live bot.

Usage:

  # Trace with current defaults (period=14, threshold=0.3)
  python replay_atr.py path/to/quant.log

  # Test specific params
  python replay_atr.py path/to/quant.log --period 5 --threshold 0.25

  # Mark ticks where the grid would signal SHORT/LONG (mirrors _determine_zone)
  python replay_atr.py path/to/quant.log --upper-limit 4.20 --lower-limit 0.00

  # Grid scan: show a table of blocked-tick % for every period × threshold combo
  python replay_atr.py path/to/quant.log --scan

  # Multiple files (glob supported)
  python replay_atr.py logs/quant.log.* --scan

  # Suppress per-tick trace (useful with --scan)
  python replay_atr.py path/to/quant.log --scan --no-trace
"""

import re
import ast
import sys
import glob
import argparse
from datetime import datetime

# Matches the price_diff:compare DEBUG lines in the quant log:
#   DEBUG 2026-06-08 01:28:00,161 app...price_diff:compare:88 ... Price diff for X/Y: {...}
_LOG_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"
    r".*?price_diff:compare"
    r".*?Price diff for [^:]+:\s*(\{.*\})\s*$"
)


def parse_logs(paths):
    events = []
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = _LOG_RE.search(line.rstrip())
                    if not m:
                        continue
                    try:
                        d = ast.literal_eval(m.group(2))
                        events.append({
                            "wall_ts": datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f"),
                            "ask_diff": float(d["ask_diff"]),
                            "bid_diff": float(d["bid_diff"]),
                            "event_ts": d.get("ts"),
                        })
                    except Exception:
                        pass
        except OSError as e:
            print(f"Warning: cannot open {path}: {e}", file=sys.stderr)

    # Sort by the broker event timestamp; fall back to wall clock
    events.sort(key=lambda e: e["event_ts"] if e["event_ts"] else e["wall_ts"].timestamp() * 1000)
    return events


def simulate_atr(events, period, threshold, upper_limit=None, lower_limit=None):
    """
    Mirror the exact ATR logic from grid_bot.py:
      tr  = max(|new_ask - prev_ask|, |new_bid - prev_bid|)
      atr = alpha * tr + (1 - alpha) * atr      (EMA, starts at 0)

    Also mirrors grid_bot.py's _determine_zone():
      ask_diff >= upper_limit -> SHORT
      bid_diff <= lower_limit -> LONG
    Returns a list of per-tick result dicts.
    """
    alpha = 2.0 / (period + 1)
    atr = 0.0
    prev_ask = prev_bid = None
    results = []
    for ev in events:
        ask, bid = ev["ask_diff"], ev["bid_diff"]
        tr = None
        if prev_ask is not None:
            tr = max(abs(ask - prev_ask), abs(bid - prev_bid))
            atr = alpha * tr + (1 - alpha) * atr

        zone = None
        if upper_limit is not None and ask >= upper_limit:
            zone = "SHORT"
        elif lower_limit is not None and bid <= lower_limit:
            zone = "LONG"

        results.append({
            "wall_ts": ev["wall_ts"],
            "event_ts": ev["event_ts"],
            "ask_diff": ask,
            "bid_diff": bid,
            "tr": tr,
            "atr": atr,
            "blocked": atr > threshold,
            "zone": zone,
        })
        prev_ask, prev_bid = ask, bid
    return results


def print_trace(results, threshold, show_zone=False, p=print):
    zone_hdr = f"  {'Zone':>5s}" if show_zone else ""
    p(f"\n{'Time':12s}  {'ask_diff':>9s}  {'bid_diff':>9s}  {'TR':>7s}  {'ATR':>7s}{zone_hdr}  Status")
    p("-" * (66 + len(zone_hdr)))
    prev_blocked = False
    for r in results:
        ts_str = r["wall_ts"].strftime("%H:%M:%S.%f")[:-3]
        tr_str = f"{r['tr']:.3f}" if r["tr"] is not None else "     --"
        if r["blocked"]:
            status = "BLOCKED" + (" <-- first" if not prev_blocked else "")
        else:
            status = "ok" + (" (resumed)" if prev_blocked else "")
        zone_str = f"  {r['zone'] or '':>5s}" if show_zone else ""
        p(f"{ts_str:12s}  {r['ask_diff']:9.2f}  {r['bid_diff']:9.2f}  {tr_str:>7s}  {r['atr']:7.3f}{zone_str}  {status}")
        prev_blocked = r["blocked"]


def _summary(results, period, threshold):
    n = len(results)
    blocked = sum(1 for r in results if r["blocked"])
    peak = max((r["atr"] for r in results), default=0.0)
    crossings = sum(
        1 for i in range(1, n) if results[i]["blocked"] and not results[i - 1]["blocked"]
    )
    return {
        "period": period, "threshold": threshold,
        "n": n, "blocked": blocked,
        "pct": 100 * blocked / n if n else 0.0,
        "peak_atr": peak, "crossings": crossings,
    }


def print_scan(events, periods, thresholds, current_period, current_threshold, p=print):
    p(f"\n{'Period':>8s}  {'Threshold':>10s}  {'Blocked':>8s}  {'%Blocked':>9s}  {'PeakATR':>9s}  {'Crossings':>10s}")
    p("-" * 68)
    for period in periods:
        for t in thresholds:
            r = simulate_atr(events, period, t)
            s = _summary(r, period, t)
            marker = "  <-- current" if period == current_period and t == current_threshold else ""
            p(
                f"{period:>8d}  {t:>10.2f}  {s['blocked']:>8d}  {s['pct']:>8.1f}%"
                f"  {s['peak_atr']:>9.3f}  {s['crossings']:>10d}{marker}"
            )


def main():
    parser = argparse.ArgumentParser(
        description="Replay log price diffs to tune ATR guard parameters",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("logs", nargs="+", help="Log file(s) or glob pattern")
    parser.add_argument("--period", type=int, default=7,
                        help="ATR EMA period (default: 7, matches ATR_PERIOD env)")
    parser.add_argument("--threshold", type=float, default=0.3,
                        help="ATR block threshold (default: 0.3, matches ATR_HIGH_THRESHOLD env)")
    parser.add_argument("--upper-limit", type=float, default=None,
                        help="Grid upper_limit; ticks with ask_diff >= this are marked SHORT")
    parser.add_argument("--lower-limit", type=float, default=None,
                        help="Grid lower_limit; ticks with bid_diff <= this are marked LONG")
    parser.add_argument("--scan", action="store_true",
                        help="Grid scan: print summary table for multiple period × threshold combos")
    parser.add_argument("--scan-periods", default="3,5,7,10,14,20",
                        help="Comma-separated periods for --scan (default: 3,5,7,10,14,20)")
    parser.add_argument("--scan-thresholds", default="0.15,0.20,0.25,0.30,0.35,0.40",
                        help="Comma-separated thresholds for --scan (default: 0.15,0.20,0.25,0.30,0.35,0.40)")
    parser.add_argument("--no-trace", action="store_true",
                        help="Skip per-tick trace (useful when only the scan table is needed)")
    parser.add_argument("--output", "-o", metavar="FILE",
                        help="Output file path (default: <first-log>.atr.txt)")
    parser.add_argument("--stdout", action="store_true",
                        help="Print to stdout instead of writing a file")
    args = parser.parse_args()

    paths = []
    for pattern in args.logs:
        expanded = glob.glob(pattern)
        paths.extend(expanded if expanded else [pattern])

    events = parse_logs(paths)
    if not events:
        print("No price_diff:compare events found in the provided log files.", file=sys.stderr)
        sys.exit(1)

    if args.stdout:
        out_path = None
    else:
        if args.output:
            out_path = args.output
        elif args.scan:
            out_path = paths[0] + ".atr.txt"
        else:
            suffix = f".atr.p{args.period}_t{args.threshold}"
            if args.upper_limit is not None:
                suffix += f"_u{args.upper_limit}"
            if args.lower_limit is not None:
                suffix += f"_l{args.lower_limit}"
            out_path = f"{paths[0]}{suffix}.txt"

    out = open(out_path, "w", encoding="utf-8") if out_path else sys.stdout

    def p(*a, **kw):
        print(*a, **kw, file=out)

    try:
        _run(args, events, paths, p)
    finally:
        if out_path:
            out.close()
            print(f"Output written to {out_path}")


def _run(args, events, paths, p):
    p(f"Loaded {len(events)} price_diff events from {len(paths)} file(s).")

    if args.scan:
        try:
            periods = [int(x) for x in args.scan_periods.split(",")]
            thresholds = [float(x) for x in args.scan_thresholds.split(",")]
        except ValueError as e:
            print(f"Bad --scan-periods or --scan-thresholds: {e}", file=sys.stderr)
            sys.exit(1)
        print_scan(events, periods, thresholds, args.period, args.threshold, p)

    show_zone = args.upper_limit is not None or args.lower_limit is not None
    results = simulate_atr(events, args.period, args.threshold, args.upper_limit, args.lower_limit)
    s = _summary(results, args.period, args.threshold)
    p(f"\nSimulation  period={args.period}  threshold={args.threshold}")
    p(f"  Ticks: {s['n']}  Blocked: {s['blocked']} ({s['pct']:.1f}%)  "
      f"Peak ATR: {s['peak_atr']:.3f}  Crossings: {s['crossings']}")

    if show_zone:
        shorts = sum(1 for r in results if r["zone"] == "SHORT")
        longs = sum(1 for r in results if r["zone"] == "LONG")
        shorts_blocked = sum(1 for r in results if r["zone"] == "SHORT" and r["blocked"])
        longs_blocked = sum(1 for r in results if r["zone"] == "LONG" and r["blocked"])
        p(f"  Zones (upper={args.upper_limit}, lower={args.lower_limit}): "
          f"SHORT={shorts} ({100 * shorts / s['n']:.1f}%, {shorts_blocked} blocked)  "
          f"LONG={longs} ({100 * longs / s['n']:.1f}%, {longs_blocked} blocked)")

    if not args.no_trace:
        print_trace(results, args.threshold, show_zone, p)


if __name__ == "__main__":
    main()
