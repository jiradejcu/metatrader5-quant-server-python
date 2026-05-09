import re
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

LOG_FILE = "/app/logs/quant_price_diff.log"


def plot_price_diff(
    log_file: str = LOG_FILE,
    time_from: datetime = None,
    time_to: datetime = None,
    out_file: str = "/app/logs/price_diff_comparison.png",
):
    price_diff_re = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
        r"app\.quant\.algorithms\.arbitrage\.price_diff.*"
        r"'ask_diff': ([\d.]+)"
    )
    grid_bot_re = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
        r"app\.quant\.algorithms\.arbitrage\.grid_bot:_process_tick:\d+.*"
        r"ask_diff=([\d.]+)"
    )

    price_diff_times, price_diff_values = [], []
    grid_bot_times, grid_bot_values = [], []

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

    print(f"price_diff points: {len(price_diff_times)}")
    print(f"grid_bot points:   {len(grid_bot_times)}")

    fig, ax = plt.subplots(figsize=(18, 6))

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


def plot_sim_price_diff(
    log_file: str,
    out_file: str = "/app/logs/sim_price_diff.png",
):
    """Parse simulate_bot stdout log and plot published vs consumed ask_diff.

    Three series:
      - published  : every tick the simulator sent to Redis
      - consumed   : ticks the grid_bot accepted (Price diff updated)
      - dropped    : ticks rejected as stale (marked with red X)
    """
    ts_pat = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"
    published_re = re.compile(
        ts_pat + r".*Tick published\s+upper=([+-]?[\d.]+)"
    )
    consumed_re = re.compile(
        ts_pat + r".*\[PubSub\] Price diff updated: upper=([\d.]+)"
    )
    dropped_re = re.compile(
        ts_pat + r".*Stale price_diff dropped: age=([\d.]+)ms.*ask_diff=([\d.]+)"
    )

    pub_times, pub_values = [], []
    con_times, con_values = [], []
    drop_times, drop_values = [], []

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
                con_values.append(float(m.group(2)))
                continue
            m = dropped_re.search(line)
            if m:
                drop_times.append(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f"))
                drop_values.append(float(m.group(3)))  # group(2)=age_ms, group(3)=ask_diff

    print(f"published: {len(pub_times)}  consumed: {len(con_times)}  dropped: {len(drop_times)}")

    fig, ax = plt.subplots(figsize=(14, 5))

    ax.plot(pub_times, pub_values, color='steelblue', linewidth=1.2, marker='o',
            markersize=5, label='published (simulator → Redis)')
    ax.plot(con_times, con_values, color='seagreen', linewidth=1.2, marker='o',
            markersize=5, linestyle='--', label='consumed by grid_bot')
    if drop_times:
        ax.scatter(drop_times, drop_values, color='tomato', marker='x', s=120,
                   linewidths=2, zorder=5, label='dropped (stale)')

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


def plot_sim_comparison(
    before_log: str,
    after_log: str,
    out_file: str = "/app/logs/sim_comparison.png",
):
    """Side-by-side comparison: before fix (all stale accepted) vs after fix (stale dropped)."""

    def _parse(log_file):
        ts_pat = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"
        pub_re = re.compile(ts_pat + r".*Tick published\s+upper=([+-]?[\d.]+)")
        con_re = re.compile(ts_pat + r".*\[PubSub\] Price diff updated: upper=([\d.]+)")
        drop_re = re.compile(ts_pat + r".*Stale price_diff dropped: age=([\d.]+)ms.*ask_diff=([\d.]+)")
        pub_t, pub_v, con_t, con_v, drop_t, drop_v = [], [], [], [], [], []
        with open(log_file) as f:
            for line in f:
                m = pub_re.search(line)
                if m:
                    pub_t.append(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f"))
                    pub_v.append(float(m.group(2)))
                    continue
                m = con_re.search(line)
                if m:
                    con_t.append(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f"))
                    con_v.append(float(m.group(2)))
                    continue
                m = drop_re.search(line)
                if m:
                    drop_t.append(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f"))
                    drop_v.append(float(m.group(3)))
        return pub_t, pub_v, con_t, con_v, drop_t, drop_v

    before = _parse(before_log)
    after  = _parse(after_log)

    print(f"BEFORE  published={len(before[0])}  consumed={len(before[2])}  dropped={len(before[4])}")
    print(f"AFTER   published={len(after[0])}   consumed={len(after[2])}   dropped={len(after[4])}")

    fig, axes = plt.subplots(1, 2, figsize=(20, 5), sharey=True)

    for ax, (pub_t, pub_v, con_t, con_v, drop_t, drop_v), title in zip(
        axes,
        [before, after],
        ["BEFORE fix — stale ticks consumed by grid_bot",
         "AFTER fix  — stale ticks dropped"],
    ):
        ax.plot(pub_t, pub_v, color='steelblue', linewidth=1.2, marker='o',
                markersize=5, label=f'published ({len(pub_t)})')
        ax.plot(con_t, con_v, color='seagreen', linewidth=1.2, marker='o',
                markersize=5, linestyle='--', label=f'consumed ({len(con_t)})')
        if drop_t:
            ax.scatter(drop_t, drop_v, color='tomato', marker='x', s=140,
                       linewidths=2.5, zorder=5, label=f'dropped ({len(drop_t)})')
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate()
        ax.set_title(title, fontsize=12)
        ax.set_xlabel('Time')
        ax.set_ylabel('ask_diff')
        ax.legend()
        ax.grid(True, alpha=0.3)

    plt.suptitle('Stale price_diff protection — before vs after commit dbc28e2', fontsize=13, y=1.02)
    plt.tight_layout()
    plt.savefig(out_file, dpi=150, bbox_inches='tight')
    print(f"Saved to {out_file}")


if __name__ == "__main__":
    if "--sim-log" in sys.argv:
        idx = sys.argv.index("--sim-log")
        log = sys.argv[idx + 1]
        out = sys.argv[idx + 2] if idx + 2 < len(sys.argv) else "/app/logs/sim_price_diff.png"
        plot_sim_price_diff(log_file=log, out_file=out)
    elif "--compare" in sys.argv:
        idx = sys.argv.index("--compare")
        before = sys.argv[idx + 1]
        after  = sys.argv[idx + 2]
        out    = sys.argv[idx + 3] if idx + 3 < len(sys.argv) else "/app/logs/sim_comparison.png"
        plot_sim_comparison(before_log=before, after_log=after, out_file=out)
    else:
        plot_price_diff(
            time_from=datetime(2026, 5, 4, 11, 35),
            time_to=datetime(2026, 5, 4, 11, 45),
        )
