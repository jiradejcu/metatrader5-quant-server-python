#!/usr/bin/env python3
"""Extract log lines between start and end timestamps."""

import argparse
import re
import sys
from pathlib import Path
from datetime import datetime

TIMESTAMP_RE = re.compile(
    r"^(?:DEBUG|INFO|WARNING|ERROR|CRITICAL) (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
)
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def resolve_ts(time_str: str, date: str) -> datetime:
    s = time_str.strip()
    if len(s) <= 8:
        s = f"{date} {s}"
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def extract(log_file: str, start: str, end: str) -> None:
    log_path = Path(log_file)
    if not log_path.exists():
        print(f"File not found: {log_path}", file=sys.stderr)
        sys.exit(1)

    m = DATE_RE.search(log_path.name)
    if not m:
        print("Cannot infer date from filename. Use full timestamp.", file=sys.stderr)
        sys.exit(1)
    date = m.group(1)

    start_dt = resolve_ts(start, date)
    end_dt   = resolve_ts(end, date) if end else None

    suffix = start.replace(":", "")
    if end:
        suffix += "_to_" + end.replace(":", "")
    out_path = log_path.with_name(log_path.name + f".{suffix}.log")

    written = 0
    in_range = False

    with log_path.open(encoding="utf-8", errors="replace") as fin, \
         out_path.open("w", encoding="utf-8") as fout:

        for line in fin:
            m = TIMESTAMP_RE.match(line)
            if m:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                if ts < start_dt:
                    in_range = False
                    continue
                if end_dt and ts > end_dt:
                    break
                in_range = True

            if in_range:
                fout.write(line)
                written += 1

    print(f"Wrote {written:,} lines → {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract log lines between two timestamps.")
    parser.add_argument("log_file", help="Path to the log file")
    parser.add_argument("start", help='Start timestamp, e.g. "2026-05-28 14:00:00"')
    parser.add_argument("end", nargs="?", default="", help='End timestamp (optional), e.g. "2026-05-28 16:00:00"')
    args = parser.parse_args()

    extract(args.log_file, args.start, args.end)
