"""Command-line utilities that talk to the running MT5 terminal.

Runs inside the mt5 container under Wine's Python, alongside the Flask API:
    wine python /app/cli.py <command> [args]
From a workstation, use script/run_mt5_cli.sh, which runs it over ssh and
downloads any files it writes.

Commands only read from the terminal; none of them trade.
Files are written to $CLI_OUT (default /config/cli/out).
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta

import MetaTrader5 as mt5

# Under Wine, Python sees the Linux filesystem as drive Z:.
OUT_DIR = os.environ.get("CLI_OUT", "/config/cli/out")


def connect():
    if not mt5.initialize():
        sys.exit(f"MT5 initialize failed: {mt5.last_error()}")
    return mt5.account_info()


def to_dicts(rows):
    return [r._asdict() for r in (rows or ())]


def write_csv(name, rows):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    print(f"{name}: {len(rows)} rows")


def parse_date(s):
    return datetime.fromisoformat(s)


def cmd_account(args):
    print(json.dumps(connect()._asdict(), indent=2, default=str))


def cmd_positions(args):
    connect()
    print(json.dumps(to_dicts(mt5.positions_get()), indent=2, default=str))


def cmd_export_history(args):
    acc = connect()
    print(f"account {acc.login} {acc.server}")
    # A far-future end date makes history_*_get return nothing, so the
    # default stops just past now.
    start = args.date_from
    end = args.date_to or datetime.now() + timedelta(days=2)
    write_csv(f"{acc.login}_deals.csv", to_dicts(mt5.history_deals_get(start, end)))
    write_csv(f"{acc.login}_orders.csv", to_dicts(mt5.history_orders_get(start, end)))
    write_csv(f"{acc.login}_open_positions.csv", to_dicts(mt5.positions_get()))


def main():
    p = argparse.ArgumentParser(prog="cli", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("account", help="print the logged-in account as JSON").set_defaults(func=cmd_account)
    sub.add_parser("positions", help="print open positions as JSON").set_defaults(func=cmd_positions)

    h = sub.add_parser("export-history", help="write deals, orders and open positions to CSV")
    h.add_argument("--from", dest="date_from", type=parse_date, default=datetime(2010, 1, 1),
                   help="start date, ISO format (default 2010-01-01)")
    h.add_argument("--to", dest="date_to", type=parse_date, default=None,
                   help="end date, ISO format (default now)")
    h.set_defaults(func=cmd_export_history)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
