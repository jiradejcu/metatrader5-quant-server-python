import re
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
        r"app\.quant\.algorithms\.arbitrage\.grid_bot:_process_tick:108.*"
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


if __name__ == "__main__":
    plot_price_diff(
        time_from=datetime(2026, 5, 4, 11, 35),
        time_to=datetime(2026, 5, 4, 11, 45),
    )
