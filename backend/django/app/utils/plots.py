import os
import re
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime


def _log_stem(log_file: str) -> str:
    """Filename of a log file without its directory, for use in plot output names."""
    return os.path.basename(log_file)


def plot_price_diff(
    log_file: str,
    time_from: datetime = None,
    time_to: datetime = None,
    out_file: str = None,
):
    if out_file is None:
        out_file = f"/app/logs/price_diff_{_log_stem(log_file)}.png"

    price_diff_re = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
        r"app\.quant\.algorithms\.arbitrage\.price_diff.*"
        r"'ask_diff': ([-\d.]+)"
    )
    grid_bot_re = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
        r"app\.quant\.algorithms\.arbitrage\.grid_bot:_process_tick:\d+.*"
        r"ask_diff=([-\d.]+)"
    )
    stale_re = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
        r"app\.quant\.algorithms\.arbitrage\.price_diff.*"
        r"Stale (primary|hedge) ticker for \S+: ([\d.]+)ms old"
    )

    price_diff_times, price_diff_values = [], []
    grid_bot_times, grid_bot_values = [], []
    primary_stale_times, hedge_stale_times = [], []

    with open(log_file) as f:
        for line in f:
            m = price_diff_re.search(line)
            if m:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f")
                price_diff_times.append(ts)
                price_diff_values.append(float(m.group(2)))
                continue
            m = grid_bot_re.search(line)
            if m:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f")
                grid_bot_times.append(ts)
                grid_bot_values.append(float(m.group(2)))
                continue
            m = stale_re.search(line)
            if m:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f")
                if m.group(2) == "primary":
                    primary_stale_times.append(ts)
                else:
                    hedge_stale_times.append(ts)

    print(f"price_diff points:    {len(price_diff_times)}")
    print(f"grid_bot points:      {len(grid_bot_times)}")
    print(f"primary stale events: {len(primary_stale_times)}")
    print(f"hedge stale events:   {len(hedge_stale_times)}")

    fig, ax = plt.subplots(figsize=(18, 6))

    for i, t in enumerate(primary_stale_times):
        ax.axvline(t, color='orange', linewidth=0.4, alpha=0.25, zorder=0,
                   label='primary stale' if i == 0 else None)
    for i, t in enumerate(hedge_stale_times):
        ax.axvline(t, color='mediumpurple', linewidth=0.4, alpha=0.25, zorder=0,
                   label='hedge stale' if i == 0 else None)

    ax.plot(price_diff_times, price_diff_values, color='steelblue', linewidth=0.8,
            alpha=0.9, label='price_diff module (ask_diff)')
    ax.plot(grid_bot_times, grid_bot_values, color='tomato', linewidth=0.8,
            alpha=0.7, linestyle='--', label='grid_bot consumed (ask_diff)')

    if time_from and time_to:
        ax.set_xlim(time_from, time_to)

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate()

    title_range = (
        f" — {time_from.strftime('%Y-%m-%d')} ({time_from.strftime('%H:%M')}–{time_to.strftime('%H:%M')})"
        if time_from and time_to else ""
    )
    ax.set_title(f'ask_diff: price_diff module vs grid_bot consumed{title_range}', fontsize=13)
    ax.set_xlabel('Time')
    ax.set_ylabel('ask_diff')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_file, dpi=150)
    print(f"Saved to {out_file}")


def plot_pubsub_flow(
    log_file: str,
    out_file: str = None,
):
    """Parse bot log and plot published vs consumed ask_diff.

    Three series:
      - published   : every tick sent to Redis
      - consumed    : ticks the grid_bot accepted in the PubSub loop
      - stale skip  : reconcile calls skipped due to stale price (marked with red X,
                      plotted at the y-value of the most recently consumed ask_diff)
    """
    if out_file is None:
        out_file = f"/app/logs/pubsub_flow_{_log_stem(log_file)}.png"

    ts_pat = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"
    published_re = re.compile(
        ts_pat + r".*Tick published\s+upper=([+-]?[\d.]+)"
    )
    consumed_re = re.compile(
        ts_pat + r".*\[PubSub\] Price diff updated: ask_diff=([+-]?[\d.]+)"
    )
    dropped_re = re.compile(
        ts_pat + r".*Price diff is stale \((\d+(?:\.\d+)?)ms > \d+(?:\.\d+)?ms\)"
    )

    pub_times, pub_values = [], []
    con_times, con_values = [], []
    drop_times, drop_values = [], []
    last_ask_diff = 0.0

    with open(log_file) as f:
        for line in f:
            m = published_re.search(line)
            if m:
                pub_times.append(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f"))
                pub_values.append(float(m.group(2)))
                continue
            m = consumed_re.search(line)
            if m:
                con_times.append(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f"))
                val = float(m.group(2))
                con_values.append(val)
                last_ask_diff = val
                continue
            m = dropped_re.search(line)
            if m:
                drop_times.append(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f"))
                drop_values.append(last_ask_diff)

    print(f"published: {len(pub_times)}  consumed: {len(con_times)}  stale skips: {len(drop_times)}")

    fig, ax = plt.subplots(figsize=(14, 5))

    ax.plot(pub_times, pub_values, color='steelblue', linewidth=1.2, marker='o',
            markersize=5, label='published (→ Redis)')
    ax.plot(con_times, con_values, color='seagreen', linewidth=1.2, marker='o',
            markersize=5, linestyle='--', label='consumed by grid_bot')
    if drop_times:
        ax.scatter(drop_times, drop_values, color='tomato', marker='x', s=120,
                   linewidths=2, zorder=5, label='stale skip (reconcile skipped)')

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate()

    ax.set_title('Stale price_diff protection — published vs consumed ask_diff', fontsize=13)
    ax.set_xlabel('Time')
    ax.set_ylabel('ask_diff')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_file, dpi=150)
    print(f"Saved to {out_file}")



def plot_stale_ticker(
    log_file: str,
    side: str = "both",          # "primary", "hedge", or "both"
    time_from: datetime = None,
    time_to: datetime = None,
    out_file: str = None,
):
    """Plot ticker age (ms) over time for stale ticker events.

    side="primary"  — only primary ticker stale events
    side="hedge"    — only hedge ticker stale events
    side="both"     — both series on the same axes
    """
    if side not in ("primary", "hedge", "both"):
        raise ValueError(f"side must be 'primary', 'hedge', or 'both', got {side!r}")

    if out_file is None:
        out_file = f"/app/logs/stale_ticker_{side}_{_log_stem(log_file)}.png"

    stale_re = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
        r".*Stale (primary|hedge) ticker for \S+: ([\d.]+)ms old"
    )

    primary_times, primary_ages = [], []
    hedge_times,   hedge_ages   = [], []

    with open(log_file) as f:
        for line in f:
            m = stale_re.search(line)
            if not m:
                continue
            ts   = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f")
            which = m.group(2)
            age  = float(m.group(3))
            if which == "primary":
                primary_times.append(ts)
                primary_ages.append(age)
            else:
                hedge_times.append(ts)
                hedge_ages.append(age)

    print(f"primary stale events: {len(primary_times)}")
    print(f"hedge   stale events: {len(hedge_times)}")

    fig, ax = plt.subplots(figsize=(18, 6))

    if side in ("primary", "both") and primary_times:
        ax.scatter(primary_times, primary_ages, color='steelblue', s=4, alpha=0.5,
                   label=f'primary ticker age ({len(primary_times)} events)')
    if side in ("hedge", "both") and hedge_times:
        ax.scatter(hedge_times, hedge_ages, color='tomato', s=4, alpha=0.5,
                   label=f'hedge ticker age ({len(hedge_times)} events)')

    if time_from and time_to:
        ax.set_xlim(time_from, time_to)

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate()

    side_label = {"primary": "primary", "hedge": "hedge", "both": "primary & hedge"}[side]
    title_range = (
        f" — {time_from.strftime('%Y-%m-%d')} ({time_from.strftime('%H:%M')}–{time_to.strftime('%H:%M')})"
        if time_from and time_to else ""
    )
    ax.set_title(f'Stale ticker age — {side_label}{title_range}', fontsize=13)
    ax.set_xlabel('Time')
    ax.set_ylabel('Ticker age (ms)')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_file, dpi=150)
    print(f"Saved to {out_file}")


if __name__ == "__main__":
    if "--pubsub-flow" in sys.argv:
        idx = sys.argv.index("--pubsub-flow")
        log = sys.argv[idx + 1]
        out = sys.argv[idx + 2] if idx + 2 < len(sys.argv) else None
        plot_pubsub_flow(log_file=log, out_file=out)
    elif "--price-diff" in sys.argv:
        idx = sys.argv.index("--price-diff")
        log = sys.argv[idx + 1]
        out = sys.argv[idx + 2] if idx + 2 < len(sys.argv) else None
        plot_price_diff(log_file=log, out_file=out)
    elif "--stale-ticker" in sys.argv:
        idx = sys.argv.index("--stale-ticker")
        log  = sys.argv[idx + 1]
        side = sys.argv[idx + 2] if idx + 2 < len(sys.argv) and sys.argv[idx + 2] in ("primary", "hedge", "both") else "both"
        out  = sys.argv[idx + 3] if idx + 3 < len(sys.argv) and sys.argv[idx + 2] in ("primary", "hedge", "both") else (sys.argv[idx + 2] if idx + 2 < len(sys.argv) and sys.argv[idx + 2] not in ("primary", "hedge", "both") else None)
        plot_stale_ticker(log_file=log, side=side, out_file=out)
