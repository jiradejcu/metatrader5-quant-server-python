import os
import re
import ast
import sys
import bisect
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta

_STALE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
    r".*Stale (primary|hedge) ticker for (\S+): ([\d.]+)ms old"
)


def parse_stale_events(log_file: str, side: str = "both"):
    """Yield (which, symbol, log_dt, event_dt, age_ms) from 'Stale ticker' log lines.

    price_diff logs ``Stale <side> ticker for <SYMBOL>: <age>ms old`` where
    age = now_ms - event_ts, so ``event_ts ≈ log_time - age``. A flat event_dt
    means the price froze; a slowly-rising one means the consumer is backlogged.
    """
    with open(log_file) as f:
        for line in f:
            m = _STALE_RE.search(line)
            if not m:
                continue
            which = m.group(2)
            if side != "both" and which != side:
                continue
            log_dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f")
            age = float(m.group(4))
            yield which, m.group(3), log_dt, log_dt - timedelta(milliseconds=age), age


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



def plot_stale_age(
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
        out_file = f"/app/logs/stale_age_{side}_{_log_stem(log_file)}.png"

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


def plot_ticker_lag(
    log_file: str,
    side: str = "primary",
    time_from: datetime = None,
    time_to: datetime = None,
    out_file: str = None,
):
    """Plot reconstructed ticker event_ts vs wall-clock time (lag / freeze view).

    The dashed diagonal is zero-lag (event_ts == wall clock). The vertical gap
    below it is the lag (staleness); flat horizontal runs mean the price froze
    while real time kept moving.
    """
    if out_file is None:
        out_file = f"/app/logs/ticker_lag_{side}_{_log_stem(log_file)}.png"

    log_times, event_times, ages = [], [], []
    for _which, _symbol, log_dt, event_dt, age in parse_stale_events(log_file, side):
        log_times.append(log_dt)
        event_times.append(event_dt)
        ages.append(age)
    print(f"{side} stale events: {len(log_times)}")
    if not log_times:
        print("nothing to plot")
        return

    fig, ax = plt.subplots(figsize=(18, 6))

    # zero-age reference (event_ts == wall clock)
    lo, hi = min(log_times), max(log_times)
    ax.plot([lo, hi], [lo, hi], color='gray', linestyle='--', linewidth=1,
            alpha=0.7, label='zero age (event_ts = wall clock)')

    sc = ax.scatter(log_times, event_times, c=ages, cmap='inferno_r', s=6,
                    label=f'{side} event_ts ({len(log_times)} events)')
    cbar = fig.colorbar(sc, ax=ax)
    cbar.set_label('ticker age (ms)')

    if time_from and time_to:
        # event_ts ≈ wall clock, so constrain y to the same window to make
        # the (sub-minute) staleness deviations from the diagonal visible.
        ax.set_xlim(time_from, time_to)
        ax.set_ylim(time_from, time_to)

    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        axis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate()

    title_range = (
        f" — {time_from.strftime('%Y-%m-%d')} ({time_from.strftime('%H:%M')}–{time_to.strftime('%H:%M')})"
        if time_from and time_to else ""
    )
    ax.set_title(f'Reconstructed {side} ticker event_ts vs wall clock{title_range}', fontsize=13)
    ax.set_xlabel('Wall-clock time (log timestamp)')
    ax.set_ylabel('Reconstructed event_ts')
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_file, dpi=150)
    print(f"Saved to {out_file}")


def plot_atr(
    log_file: str,
    threshold: float = 0.3,
    time_from: datetime = None,
    time_to: datetime = None,
    out_file: str = None,
):
    """Plot the grid_bot ATR volatility guard alongside price diff.

    Overlaid series on a shared time axis:
      - left axis       : ask_diff / bid_diff consumed by the grid_bot, plus the
                          grid limits stepped from the latest grid settings seen
                          in the log — entry limits (short_upper for a short
                          entry, long_lower for a long entry) and exit limits
                          (long_upper to close a long, short_lower to close a
                          short). Actual executions are marked here too as
                          outline triangles: ▲ BUY / ▼ SELL, black edge = opening
                          the position, crimson edge = closing.
      - right axis      : running ATR and its ATR_HIGH_THRESHOLD line.
      - 2nd right axis  : current position size (signed lots) from the
                          ``position=…`` log, stepped between snapshots.

    ask_diff / bid_diff / atr all come from the same ``[PubSub] Price diff
    updated: …`` line, so they are perfectly time-aligned. Three event overlays:

      - ATR above threshold : the ticks where the ATR guard actually tripped,
        counted from the ``[Grid] Abort (high volatility …)`` log lines. ATR is
        the first abort check in grid_bot, so every such abort is genuinely
        ATR-caused (not stale-price / multi-order).

      - blocked entry : the subset where ATR was above threshold *and* the price
        diff had breached an entry limit (ask_diff >= short_upper or
        bid_diff <= long_lower) — i.e. a trade would have been opened if the ATR
        guard hadn't stopped it.

      - blocked exit : ATR above threshold *and* price past an exit limit
        *and* the matching position is actually open — a long exit
        (ask_diff >= long_upper) only counts while holding a long (position > 0),
        a short exit (bid_diff <= short_lower) only while holding a short
        (position < 0). Position is read from the ``position=…`` line grid_bot
        logs each tick before the abort check, carried forward between logs.

    Entry vs exit is resolved by position (mirrors grid_bot's _determine_zone +
    _compute_target): a SELL closes a long when position > 0 but opens a short
    otherwise; a BUY closes a short when position < 0 but opens a long otherwise.

    There is no per-event log of the grid limit, so the latest grid settings in
    effect at each tick are assumed.
    """
    if out_file is None:
        out_file = f"/app/logs/atr_{_log_stem(log_file)}.png"

    ts_pat = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"
    tick_re = re.compile(
        ts_pat + r".*\[PubSub\] Price diff updated: "
        r"ask_diff=([+-]?[\d.]+), bid_diff=([+-]?[\d.]+), atr=([\d.]+)"
    )
    # ATR is checked first in grid_bot's abort chain, so a "high volatility"
    # abort is always attributable to ATR alone.
    abort_re = re.compile(
        ts_pat + r".*\[Grid\] Abort \(high volatility \(ATR=([\d.]+)"
    )
    settings_re = re.compile(
        ts_pat + r".*\[PubSub\] Grid settings updated: (\{.*\})\s*$"
    )
    # grid_bot logs this in _process_tick right before the abort check, so the
    # position is available even on high-ATR (aborted) ticks.
    position_re = re.compile(
        ts_pat + r".*position=([+-]?[\d.]+) open_orders="
    )
    # Actual executions reported on the user data stream (FILLED / PARTIALLY_FILLED).
    fill_re = re.compile(
        ts_pat + r".*\[UserDataStream\] Order [A-Z_]+: side=(\w+) "
        r"fill_price=([\d.]+) avg_price=[\d.]+ qty=([\d.]+)/[\d.]+ order_id="
    )

    times, ask_diffs, bid_diffs, atrs = [], [], [], []
    abort_times, abort_atrs = [], []
    settings_times, settings_vals = [], []   # chronological grid-settings changes
    position_times, position_vals = [], []   # chronological position snapshots
    fill_times, fill_sides, fill_qtys = [], [], []   # actual executions
    with open(log_file) as f:
        for line in f:
            m = tick_re.search(line)
            if m:
                times.append(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f"))
                ask_diffs.append(float(m.group(2)))
                bid_diffs.append(float(m.group(3)))
                atrs.append(float(m.group(4)))
                continue
            m = abort_re.search(line)
            if m:
                abort_times.append(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f"))
                abort_atrs.append(float(m.group(2)))
                continue
            m = position_re.search(line)
            if m:
                position_times.append(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f"))
                position_vals.append(float(m.group(2)))
                continue
            m = fill_re.search(line)
            if m:
                fill_times.append(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f"))
                fill_sides.append(m.group(2))
                fill_qtys.append(float(m.group(3)))
                continue
            m = settings_re.search(line)
            if m:
                try:
                    settings_vals.append(ast.literal_eval(m.group(2)))
                    settings_times.append(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f"))
                except (ValueError, SyntaxError):
                    pass

    if not times:
        print("nothing to plot")
        return

    def _settings_at(t):
        """Latest grid settings in effect at time t (assume the first-known
        settings for ticks that precede any settings line)."""
        if not settings_times:
            return None
        i = bisect.bisect_right(settings_times, t) - 1
        return settings_vals[max(i, 0)]

    def _position_at(t):
        """Latest logged position at time t; 0.0 (flat) before the first log."""
        if not position_times:
            return 0.0
        i = bisect.bisect_right(position_times, t) - 1
        return position_vals[i] if i >= 0 else 0.0

    # Per-tick grid limits (stepped) and the blocked entry/exit masks.
    short_upper_arr, long_lower_arr = [], []   # entry limits
    long_upper_arr, short_lower_arr = [], []   # exit limits
    entry_times, entry_vals = [], []
    exit_times, exit_vals = [], []
    for t, ask, bid, atr in zip(times, ask_diffs, bid_diffs, atrs):
        s = _settings_at(t)
        su = s["short_upper"] if s else None
        ll = s["long_lower"] if s else None
        lu = s["long_upper"] if s else None
        sl = s["short_lower"] if s else None
        short_upper_arr.append(su)
        long_lower_arr.append(ll)
        long_upper_arr.append(lu)
        short_lower_arr.append(sl)
        if s is None or atr <= threshold:
            continue
        pos = _position_at(t)
        # Resolve entry vs exit by position, mirroring _determine_zone +
        # _compute_target: a SELL closes a long (exit) only when position > 0,
        # else opens a short (entry); a BUY closes a short (exit) only when
        # position < 0, else opens a long (entry). Exit conditions are checked
        # first so they win over the entry limit when the position is held.
        if pos > 0 and ask >= lu:        # SELL closes the open long → exit
            exit_times.append(t); exit_vals.append(ask)
        elif pos < 0 and bid <= sl:      # BUY closes the open short → exit
            exit_times.append(t); exit_vals.append(bid)
        elif ask >= su:                  # short entry would have opened
            entry_times.append(t); entry_vals.append(ask)
        elif bid <= ll:                  # long entry would have opened
            entry_times.append(t); entry_vals.append(bid)

    n_above = len(abort_times)       # ATR guard actually tripped
    n_entry = len(entry_times)       # ... and a trade would have opened
    n_exit = len(exit_times)         # ... and the held position could have closed
    print(f"atr points: {len(times)}  "
          f"ATR above threshold (grid aborts): {n_above}  "
          f"blocked entry (past entry limit): {n_entry}  "
          f"blocked exit (past exit limit, position held): {n_exit}")
    if not position_times:
        print("warning: no 'position=' lines found — cannot confirm the held "
              "position, blocked-exit count is 0")
    if not settings_times:
        print("warning: no '[PubSub] Grid settings updated' lines found — "
              "cannot determine grid limits, blocked-entry/exit counts are 0")

    # Actual fills, placed on the price-diff axis at the spread current when they
    # executed (BUY near bid_diff, SELL near ask_diff). Open vs close is decided
    # by the position held just before the fill: a fill that grows abs(position)
    # opens, one that shrinks it closes.
    def _pricediff_at(t, side):
        i = max(bisect.bisect_right(times, t) - 1, 0)
        return bid_diffs[i] if side == "BUY" else ask_diffs[i]

    buy_open_t, buy_open_v = [], []
    buy_close_t, buy_close_v = [], []
    sell_open_t, sell_open_v = [], []
    sell_close_t, sell_close_v = [], []
    for ft, side, qty in zip(fill_times, fill_sides, fill_qtys):
        v = _pricediff_at(ft, side)
        pos_before = _position_at(ft)
        signed = qty if side == "BUY" else -qty
        is_open = pos_before == 0 or (pos_before > 0) == (signed > 0)
        if side == "BUY":
            (buy_open_t if is_open else buy_close_t).append(ft)
            (buy_open_v if is_open else buy_close_v).append(v)
        else:
            (sell_open_t if is_open else sell_close_t).append(ft)
            (sell_open_v if is_open else sell_close_v).append(v)
    n_open = len(buy_open_t) + len(sell_open_t)
    n_close = len(buy_close_t) + len(sell_close_t)
    print(f"fills: {len(fill_times)}  (open: {n_open}, close: {n_close})")

    fig, ax = plt.subplots(figsize=(18, 6))
    ax2 = ax.twinx()
    ax3 = ax.twinx()
    ax3.spines['right'].set_position(('outward', 55))

    # ── left axis: price diff consumed by the grid bot ──
    ax.plot(times, ask_diffs, color='steelblue', linewidth=0.8, alpha=0.9,
            label='ask_diff (consumed)')
    ax.plot(times, bid_diffs, color='seagreen', linewidth=0.8, alpha=0.6,
            label='bid_diff (consumed)')
    if settings_times:
        ax.plot(times, short_upper_arr, color='steelblue', linewidth=1,
                linestyle=':', alpha=0.7, drawstyle='steps-post',
                label='short_upper (short entry limit)')
        ax.plot(times, long_lower_arr, color='seagreen', linewidth=1,
                linestyle=':', alpha=0.7, drawstyle='steps-post',
                label='long_lower (long entry limit)')
        ax.plot(times, long_upper_arr, color='steelblue', linewidth=1,
                linestyle='-.', alpha=0.5, drawstyle='steps-post',
                label='long_upper (long exit limit)')
        ax.plot(times, short_lower_arr, color='seagreen', linewidth=1,
                linestyle='-.', alpha=0.5, drawstyle='steps-post',
                label='short_lower (short exit limit)')
    ax.set_ylabel('price diff')

    # ── right axis: ATR + guard threshold ──
    ax2.plot(times, atrs, color='darkorange', linewidth=1.1, alpha=0.9, label='ATR')
    ax2.axhline(threshold, color='tomato', linestyle='--', linewidth=1,
                alpha=0.8, label=f'ATR_HIGH_THRESHOLD ({threshold})')
    ax2.set_ylabel('ATR')
    ax2.set_ylim(bottom=0)

    # ── second right axis: current position size ──
    if position_times:
        ax3.plot(position_times, position_vals, color='gray', linewidth=1.2,
                 alpha=0.7, drawstyle='steps-post', label='position (lots)')
    ax3.set_ylabel('position (lots)')

    # ── overlay 1: ATR guard tripped (aborts) ──
    if abort_times:
        ax2.scatter(abort_times, abort_atrs, color='tomato', marker='o', s=14,
                    alpha=0.6, zorder=4,
                    label=f'ATR above threshold ({n_above} aborts)')

    # ── overlay 2: ATR blocked an entry (abort + price past entry limit) ──
    if entry_times:
        ax.scatter(entry_times, entry_vals, color='red', marker='x', s=45,
                   linewidths=1.4, zorder=6,
                   label=f'blocked entry ({n_entry} events)')

    # ── overlay 3: ATR blocked an exit (abort + price past exit limit) ──
    if exit_times:
        ax.scatter(exit_times, exit_vals, color='blueviolet', marker='x', s=40,
                   linewidths=1.4, zorder=6,
                   label=f'blocked exit ({n_exit}, position held)')

    # ── overlay 4: actual fills (▲ BUY / ▼ SELL, outline only; edge colour
    #    distinguishes open vs close) ──
    fkw = dict(s=32, zorder=7, linewidths=1.0, facecolors='none', alpha=0.75)
    if buy_open_t:
        ax.scatter(buy_open_t, buy_open_v, marker='^', edgecolors='black', **fkw,
                   label=f'fill BUY open ({len(buy_open_t)})')
    if buy_close_t:
        ax.scatter(buy_close_t, buy_close_v, marker='^', edgecolors='crimson', **fkw,
                   label=f'fill BUY close ({len(buy_close_t)})')
    if sell_open_t:
        ax.scatter(sell_open_t, sell_open_v, marker='v', edgecolors='black', **fkw,
                   label=f'fill SELL open ({len(sell_open_t)})')
    if sell_close_t:
        ax.scatter(sell_close_t, sell_close_v, marker='v', edgecolors='crimson', **fkw,
                   label=f'fill SELL close ({len(sell_close_t)})')

    if time_from and time_to:
        ax.set_xlim(time_from, time_to)

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate()

    title_range = (
        f" — {time_from.strftime('%Y-%m-%d')} ({time_from.strftime('%H:%M')}–{time_to.strftime('%H:%M')})"
        if time_from and time_to else ""
    )
    ax.set_title(f'grid_bot ATR guard vs price diff{title_range}', fontsize=13)
    ax.set_xlabel('Time')
    ax.grid(True, alpha=0.3)

    # merge legends from all three axes
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    lines3, labels3 = ax3.get_legend_handles_labels()
    ax.legend(lines1 + lines2 + lines3, labels1 + labels2 + labels3,
              loc='upper left', fontsize=8, ncol=2)

    plt.tight_layout()
    plt.savefig(out_file, dpi=150, bbox_inches='tight')
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
    elif "--stale-age" in sys.argv:
        idx = sys.argv.index("--stale-age")
        log  = sys.argv[idx + 1]
        side = sys.argv[idx + 2] if idx + 2 < len(sys.argv) and sys.argv[idx + 2] in ("primary", "hedge", "both") else "both"
        out  = sys.argv[idx + 3] if idx + 3 < len(sys.argv) and sys.argv[idx + 2] in ("primary", "hedge", "both") else (sys.argv[idx + 2] if idx + 2 < len(sys.argv) and sys.argv[idx + 2] not in ("primary", "hedge", "both") else None)
        plot_stale_age(log_file=log, side=side, out_file=out)
    elif "--ticker-lag" in sys.argv:
        idx = sys.argv.index("--ticker-lag")
        log  = sys.argv[idx + 1]
        side = sys.argv[idx + 2] if idx + 2 < len(sys.argv) and sys.argv[idx + 2] in ("primary", "hedge") else "primary"
        out  = sys.argv[idx + 3] if idx + 3 < len(sys.argv) and sys.argv[idx + 2] in ("primary", "hedge") else (sys.argv[idx + 2] if idx + 2 < len(sys.argv) and sys.argv[idx + 2] not in ("primary", "hedge") else None)
        plot_ticker_lag(log_file=log, side=side, out_file=out)
    elif "--atr" in sys.argv:
        idx = sys.argv.index("--atr")
        log = sys.argv[idx + 1]
        threshold = float(os.getenv("ATR_HIGH_THRESHOLD", "0.3"))
        out = sys.argv[idx + 2] if idx + 2 < len(sys.argv) else None
        plot_atr(log_file=log, threshold=threshold, out_file=out)
