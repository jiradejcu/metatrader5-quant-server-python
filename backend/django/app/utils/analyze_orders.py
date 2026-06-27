import re
import sys
import csv
from datetime import datetime

# ── Patterns ──────────────────────────────────────────────────────────────────
ts_fmt = "%Y-%m-%d %H:%M:%S,%f"

price_diff_pat = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+).*Price diff for \S+:.*?"
    r"'ask_diff': ([0-9.]+).*?'bid_diff': ([0-9.]+).*?"
    r"'primary_ask': ([0-9.]+).*?'hedge_ask': ([0-9.]+).*?"
    r"'primary_bid': ([0-9.]+).*?'hedge_bid': ([0-9.]+)"
)
filled_pat = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+).*\[UserDataStream\] Order FILLED: "
    r"side=(\w+) fill_price=([0-9.]+) avg_price=[0-9.]+ qty=([0-9.]+)/[0-9.]+ order_id=(\d+)"
)
# Order placement (the moment the order_id was first opened on the book)
placed_pat = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+).*Chase order placed: "
    r"order_id=(\d+) side=(\w+) qty=([0-9.]+) price=([0-9.]+)"
)
# MT5 new hedge (action=1): price is request[5]
hedge_new_pat = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+).*Order successful:.*?"
    r"'request': \[1, \d+, \d+, '\S+', ([0-9.]+), ([0-9.]+),"
)


# ── Functions ─────────────────────────────────────────────────────────────────

# Timestamp columns rendered as Excel times (hh:mm:ss.000).
DATE_COLS = ('fill_ts', 'placed_ts', 'pred_ts', 'hedge_ts')
DATE_FMT  = 'hh:mm:ss.000'
# Columns that get a red data-bar conditional format.
DATA_BAR_COLS = ('slippage', 'primary_edge', 'hedge_edge', 'net_edge')

# Human-readable, multi-line column headers (newlines wrap in the cell so the
# column can stay narrow). Falls back to the raw field name if not listed.
HEADERS = {
    'fill_ts'              : 'Fill\nTime',
    'side'                 : 'Side',
    'qty'                  : 'Qty',
    'order_id'            : 'Order ID',
    'placed_ts'           : 'Placed\nTime',
    'pred_ts'             : 'Pred\nTime',
    'pred_to_fill_ms'     : 'Pred→Fill\n(ms)',
    'order_age_ms'        : 'Order Age\n(ms)',
    'pred_to_hedge_ms'    : 'Pred→Hedge\n(ms)',
    'pred_primary_price'  : 'Pred\nPrimary',
    'pred_hedge_price'    : 'Pred\nHedge',
    'predicted_price_diff': 'Pred\nDiff',
    'hedge_ts'            : 'Hedge\nTime',
    'actual_primary_price': 'Actual\nPrimary',
    'actual_hedge_price'  : 'Actual\nHedge',
    'actual_price_diff'   : 'Actual\nDiff',
    'primary_price_diff'  : 'Primary\nDiff',
    'hedge_price_diff'    : 'Hedge\nDiff',
    'slippage'            : 'Slippage',
    'primary_edge'        : 'Primary\nEdge',
    'hedge_edge'          : 'Hedge\nEdge',
    'net_edge'            : 'Net\nEdge',
    'pnl'                 : 'PnL',
    'cumpnl'              : 'Cum\nPnL',
}


def _write_xlsx(out_xlsx, fieldnames, rows):
    """Write matched orders to a styled .xlsx workbook.

    - first row frozen, human-readable multi-line headers
    - timestamp columns formatted as hh:mm:ss.000
    - column widths fit their content
    - red data bars on slippage / primary_edge / hedge_edge / net_edge
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment
    from openpyxl.utils import get_column_letter
    from openpyxl.formatting.rule import DataBarRule

    wb = Workbook()
    ws = wb.active
    ws.title = 'orders'

    headers = [HEADERS.get(fn, fn) for fn in fieldnames]
    ws.append(headers)
    header_align = Alignment(wrap_text=True, horizontal='center', vertical='center')
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = header_align
    # Two lines tall so wrapped headers are fully visible.
    ws.row_dimensions[1].height = 30

    for r in rows:
        out_row = []
        for fn in fieldnames:
            v = r.get(fn, '')
            if v == '' or v is None:
                out_row.append(None)
            elif fn in DATE_COLS:
                out_row.append(datetime.strptime(v, '%Y-%m-%d %H:%M:%S.%f'))
            else:
                out_row.append(v)
        ws.append(out_row)

    ws.freeze_panes = 'A2'
    last_row = ws.max_row

    for idx, fn in enumerate(fieldnames, 1):
        col = get_column_letter(idx)

        if fn in DATE_COLS:
            for row_i in range(2, last_row + 1):
                ws[f'{col}{row_i}'].number_format = DATE_FMT

        # Width to fit content. Header contributes only its longest line, so a
        # wrapped multi-line header lets the column stay narrow.
        width = max(len(line) for line in HEADERS.get(fn, fn).split('\n'))
        for row_i in range(2, last_row + 1):
            cell = ws[f'{col}{row_i}']
            if cell.value is None:
                disp = ''
            elif fn in DATE_COLS:
                disp = '00:00:00.000'
            else:
                disp = str(cell.value)
            width = max(width, len(disp))
        ws.column_dimensions[col].width = width + 2

        if fn in DATA_BAR_COLS and last_row >= 2:
            ws.conditional_formatting.add(
                f'{col}2:{col}{last_row}',
                DataBarRule(start_type='min', end_type='max',
                            color='FF0000', showValue=True),
            )

    wb.save(out_xlsx)


def analyze_orders(log_file, out_xlsx=None):
    import os
    base = os.path.basename(log_file)
    dir_ = os.path.dirname(os.path.abspath(log_file))
    if out_xlsx is None:
        out_xlsx = os.path.join(dir_, f"{base}_orders.xlsx")
    else:
        # Always emit a real .xlsx regardless of the extension passed in.
        out_xlsx = os.path.splitext(out_xlsx)[0] + ".xlsx"
    out_log = os.path.join(dir_, f"{base}_filtered.log")

    price_diffs = []
    fills = []
    hedges_new = []
    placements = {}
    filtered_lines = []

    with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            m = price_diff_pat.search(line)
            if m:
                price_diffs.append({
                    'ts_str': m.group(1).replace(',', '.'), 'ts_dt': datetime.strptime(m.group(1), ts_fmt),
                    'ask_diff': float(m.group(2)), 'bid_diff': float(m.group(3)),
                    'primary_ask': float(m.group(4)), 'hedge_ask': float(m.group(5)),
                    'primary_bid': float(m.group(6)), 'hedge_bid': float(m.group(7)),
                })
                filtered_lines.append((price_diffs[-1]['ts_dt'], line))
                continue
            m = filled_pat.search(line)
            if m:
                fills.append({
                    'ts_str': m.group(1).replace(',', '.'), 'ts_dt': datetime.strptime(m.group(1), ts_fmt),
                    'side': m.group(2), 'fill_price': float(m.group(3)), 'qty': float(m.group(4)), 'order_id': m.group(5)
                })
                filtered_lines.append((fills[-1]['ts_dt'], line))
                continue
            m = hedge_new_pat.search(line)
            if m:
                hedges_new.append({
                    'ts_str': m.group(1).replace(',', '.'), 'ts_dt': datetime.strptime(m.group(1), ts_fmt),
                    'volume': float(m.group(2)), 'price': float(m.group(3)),
                    'used': False
                })
                filtered_lines.append((hedges_new[-1]['ts_dt'], line))
                continue
            m = placed_pat.search(line)
            if m:
                order_id = m.group(2)
                # Keep the first placement seen for this order_id.
                if order_id not in placements:
                    placements[order_id] = {
                        'ts_str': m.group(1).replace(',', '.'), 'ts_dt': datetime.strptime(m.group(1), ts_fmt),
                        'side': m.group(3), 'qty': float(m.group(4)), 'price': float(m.group(5)),
                    }
                filtered_lines.append((datetime.strptime(m.group(1), ts_fmt), line))

    filtered_lines.sort(key=lambda x: x[0])
    with open(out_log, 'w', encoding='utf-8') as f:
        f.writelines(line for _, line in filtered_lines)
    print(f"Filtered log  : {out_log}")

    print(f"Price diffs   : {len(price_diffs)}")
    print(f"Entry fills   : {len(fills)}")
    print(f"MT5 new hedges: {len(hedges_new)}")
    print(f"Order placed  : {len(placements)}")
    print()

    results = []

    for fill in fills:
        ft = fill['ts_dt']

        # The fill is reported asynchronously via the user data stream, so the
        # price diff logged just before the FILLED line is unrelated to this
        # order. Track back via order_id to when the order was first placed,
        # and use the price diff that was current at that moment instead.
        placed = placements.get(fill['order_id'])
        ref_ts = placed['ts_dt'] if placed else ft

        # Last price diff strictly before the order was placed (or before the
        # fill if no placement was found, e.g. order placed outside this log).
        pred = None
        for pd in reversed(price_diffs):
            if pd['ts_dt'] <= ref_ts:
                pred = pd
                break

        # First unused MT5 new hedge after fill (within 15 s)
        hedge = None
        for h in hedges_new:
            if h['used']:
                continue
            delta = (h['ts_dt'] - ft).total_seconds()
            if 0 <= delta <= 15:
                hedge = h
                h['used'] = True
                break

        if pred is None or hedge is None:
            results.append({'fill': fill, 'pred': pred, 'hedge': hedge, 'match': False})
            continue

        is_buy = fill['side'] == 'BUY'
        pred_primary_price     = pred['primary_bid'] if is_buy else pred['primary_ask']
        pred_hedge_price      = pred['hedge_bid'] if is_buy else pred['hedge_ask']
        predicted_price_diff  = pred['bid_diff']  if is_buy else pred['ask_diff']

        actual_primary_price = fill['fill_price']
        actual_hedge_price   = hedge['price']
        actual_price_diff    = round(actual_primary_price - actual_hedge_price, 4)
        primary_price_diff   = round(actual_primary_price - pred_primary_price, 4)
        hedge_price_diff     = round(actual_hedge_price - pred_hedge_price, 4)
        slippage             = round(actual_price_diff - predicted_price_diff, 4)

        # Re-sign vs. the order side so positive always means "better than
        # predicted" and negative always means "worse than predicted":
        #   SELL: higher primary fill / lower hedge fill is better
        #   BUY:  lower primary fill / higher hedge fill is better
        sign         = 1 if fill['side'] == 'SELL' else -1
        primary_edge = round(sign * primary_price_diff, 4)
        hedge_edge   = round(-sign * hedge_price_diff, 4)
        net_edge     = round(sign * slippage, 4)

        # Spread cash-flow locked in by this pair, in price-points x lots.
        # SELL primary collects the spread (+), BUY primary pays it (-).
        # Multiply by the instrument point value to get money.
        pnl          = round(sign * actual_price_diff * fill['qty'], 4)

        pred_to_fill_ms      = round((fill['ts_dt'] - pred['ts_dt']).total_seconds() * 1000)
        pred_to_hedge_ms     = round((hedge['ts_dt'] - pred['ts_dt']).total_seconds() * 1000)
        order_age_ms         = round((fill['ts_dt'] - placed['ts_dt']).total_seconds() * 1000) if placed else ''

        results.append({
            'fill_ts'              : fill['ts_str'],
            'side'                 : fill['side'],
            'qty'                  : fill['qty'],
            'order_id'             : fill['order_id'],
            'placed_ts'            : placed['ts_str'] if placed else '',
            'pred_ts'              : pred['ts_str'],
            'pred_to_fill_ms'      : pred_to_fill_ms,
            'order_age_ms'         : order_age_ms,
            'pred_to_hedge_ms'     : pred_to_hedge_ms,
            'pred_primary_price'   : pred_primary_price,
            'pred_hedge_price'     : pred_hedge_price,
            'predicted_price_diff' : predicted_price_diff,
            'hedge_ts'             : hedge['ts_str'],
            'actual_primary_price' : actual_primary_price,
            'actual_hedge_price'   : actual_hedge_price,
            'actual_price_diff'    : actual_price_diff,
            'primary_price_diff'   : primary_price_diff,
            'hedge_price_diff'     : hedge_price_diff,
            'slippage'             : slippage,
            'primary_edge'         : primary_edge,
            'hedge_edge'           : hedge_edge,
            'net_edge'             : net_edge,
            'pnl'                  : pnl,
            'match'                : True
        })

    matched   = [r for r in results if r['match']]
    unmatched = [r for r in results if not r['match']]

    # Running cumulative PnL in fill order.
    _cum = 0.0
    for r in matched:
        _cum = round(_cum + r['pnl'], 4)
        r['cumpnl'] = _cum

    fieldnames = [
        'fill_ts', 'side', 'qty', 'order_id', 'placed_ts', 'pred_ts',
        'pred_to_fill_ms', 'order_age_ms', 'pred_to_hedge_ms',
        'pred_primary_price', 'pred_hedge_price', 'predicted_price_diff',
        'hedge_ts', 'actual_primary_price', 'actual_hedge_price', 'actual_price_diff',
        'primary_price_diff', 'hedge_price_diff', 'slippage',
        'primary_edge', 'hedge_edge', 'net_edge', 'pnl', 'cumpnl',
    ]
    _write_xlsx(out_xlsx, fieldnames, matched)
    print(f"Written to {out_xlsx}")
    print()

    col = (
        f"{'#':<3} {'Fill Time':<26} {'S':<5} {'Qty':>8} {'Order ID':<14}"
        f"{'P→Fill':>8} {'OrderAge':>10} {'P→Hedge':>8} "
        f"{'PredPrimary':>11} {'PredHedge':>10} {'PredDiff':>9}"
        f"{'ActPrimary':>11} {'ActHedge':>10} {'ActDiff':>9}"
        f"{'PrimaryDiff':>12} {'HedgeDiff':>10} {'Slippage':>9}"
        f"{'PrimaryEdge':>12} {'HedgeEdge':>10} {'NetEdge':>9}"
        f"{'Pnl':>10} {'CumPnl':>10}"
    )
    print(col)
    print("-" * len(col))

    for i, r in enumerate(matched, 1):
        s = f"{r['slippage']:+.4f}"
        age = f"{r['order_age_ms']}ms" if r['order_age_ms'] != '' else '-'
        print(
            f"{i:<3} {r['fill_ts']:<26} {r['side']:<5} {r['qty']:>8} {r['order_id']:<14}"
            f"{r['pred_to_fill_ms']:>7}ms {age:>10} {r['pred_to_hedge_ms']:>7}ms"
            f"{r['pred_primary_price']:>11.2f} {r['pred_hedge_price']:>10.2f} {r['predicted_price_diff']:>9.2f}"
            f"{r['actual_primary_price']:>11.2f} {r['actual_hedge_price']:>10.2f} {r['actual_price_diff']:>9.4f}"
            f"{r['primary_price_diff']:>+12.4f} {r['hedge_price_diff']:>+10.4f} {s:>9}"
            f"{r['primary_edge']:>+12.4f} {r['hedge_edge']:>+10.4f} {r['net_edge']:>+9.4f}"
            f"{r['pnl']:>+10.4f} {r['cumpnl']:>+10.4f}"
        )

    print()
    if matched:
        slippages = [r['slippage'] for r in matched]
        sell_slip = [r['slippage'] for r in matched if r['side'] == 'SELL']
        buy_slip  = [r['slippage'] for r in matched if r['side'] == 'BUY']

        sep = "-" * 55
        print(sep)
        print(f"  Matched orders : {len(matched)}")
        print(f"  Avg slippage   : {sum(slippages)/len(slippages):+.4f}")
        print(f"  Min slippage   : {min(slippages):+.4f}")
        print(f"  Max slippage   : {max(slippages):+.4f}")
        if sell_slip:
            print(f"  SELL avg slip  : {sum(sell_slip)/len(sell_slip):+.4f}  "
                  f"(n={len(sell_slip)}, range [{min(sell_slip):+.4f} to {max(sell_slip):+.4f}])")
        if buy_slip:
            print(f"  BUY  avg slip  : {sum(buy_slip)/len(buy_slip):+.4f}  "
                  f"(n={len(buy_slip)}, range [{min(buy_slip):+.4f} to {max(buy_slip):+.4f}])")
        worse  = sum(1 for r in matched if r['net_edge'] < 0)
        better = sum(1 for r in matched if r['net_edge'] > 0)
        print(f"  Worse than pred: {worse}  |  Better: {better}")
        print(sep)

        # ── PnL (in price-points x lots; multiply by point value for money) ──
        # Each pair locks in a spread: SELL primary collects it, BUY pays it.
        # Realized = the flat (matched) volume, valued at the average spread
        # collected vs paid. The leftover inventory is still open and is
        # marked at the last observed spread (actual_price_diff).
        sell_qty  = sum(r['qty'] for r in matched if r['side'] == 'SELL')
        buy_qty   = sum(r['qty'] for r in matched if r['side'] == 'BUY')
        sell_val  = sum(r['actual_price_diff'] * r['qty'] for r in matched if r['side'] == 'SELL')
        buy_cost  = sum(r['actual_price_diff'] * r['qty'] for r in matched if r['side'] == 'BUY')
        avg_sell  = sell_val / sell_qty if sell_qty else 0.0
        avg_buy   = buy_cost / buy_qty if buy_qty else 0.0
        matched_qty = min(sell_qty, buy_qty)
        realized  = (avg_sell - avg_buy) * matched_qty

        mark      = matched[-1]['actual_price_diff']          # last observed spread
        net_qty   = buy_qty - sell_qty                        # +ve = net long primary
        if net_qty > 0:        # excess BUYs -> long primary, close by selling at mark
            open_qty, open_basis = net_qty, avg_buy
            unrealized = (mark - avg_buy) * net_qty
            open_desc  = f"long primary {net_qty:.3f} @ spread {avg_buy:+.4f}"
        elif net_qty < 0:      # excess SELLs -> short primary, close by buying at mark
            open_qty, open_basis = -net_qty, avg_sell
            unrealized = (avg_sell - mark) * (-net_qty)
            open_desc  = f"short primary {-net_qty:.3f} @ spread {avg_sell:+.4f}"
        else:
            open_qty, unrealized, open_desc = 0.0, 0.0, "flat"

        total_pnl = sum(r['pnl'] for r in matched)
        print("  PnL (price-points x lots; x point value = money)")
        print(f"  Avg spread SELL: {avg_sell:+.4f}  (collected, n_qty={sell_qty:g})")
        print(f"  Avg spread BUY : {avg_buy:+.4f}  (paid,      n_qty={buy_qty:g})")
        print(f"  Realized       : {realized:+.4f}  (matched {matched_qty:g} lots)")
        print(f"  Open inventory : {open_desc}")
        print(f"  Unrealized     : {unrealized:+.4f}  (marked @ last spread {mark:+.4f})")
        print(f"  MTM total      : {realized + unrealized:+.4f}")
        print(f"  Cash-flow sum  : {total_pnl:+.4f}  (= realized + open cost basis)")
        print(sep)

    if unmatched:
        print(f"\nUnmatched fills ({len(unmatched)}):")
        for r in unmatched:
            f_ = r['fill']
            print(f"  {f_['ts_str']} side={f_['side']} qty={f_['qty']} fill={f_['fill_price']}"
                  f"  pred={'YES' if r['pred'] else 'NO'} hedge={'YES' if r['hedge'] else 'NO'}")


def analyze_chase_delay(log_file, out_csv=None, symbol='XAUUSDT', threshold=0.10):
    if out_csv is None:
        import os
        base = os.path.basename(log_file)
        out_csv = os.path.join(os.path.dirname(os.path.abspath(log_file)), f"{base}_chase_delay.csv")
    chase_re = re.compile(
        r'(\d{2}:\d{2}:\d{2},\d{3}).*Chase order placed: order_id=(\d+) side=(\w+) qty=([\d.]+) price=([\d.]+)'
    )
    pdiff_re = re.compile(
        rf'(\d{{2}}:\d{{2}}:\d{{2}},\d{{3}}).*Price diff for {symbol}.*primary_ask.: ([\d.]+).*primary_bid.: ([\d.]+)'
    )

    chases = []
    pdiffs = []

    with open(log_file, encoding='utf-8', errors='replace') as f:
        for line in f:
            m = chase_re.search(line)
            if m:
                chases.append({'time': m.group(1), 'order_id': m.group(2), 'side': m.group(3),
                                'qty': m.group(4), 'price': float(m.group(5))})
            m = pdiff_re.search(line)
            if m:
                pdiffs.append({'time': m.group(1), 'primary_ask': float(m.group(2)), 'primary_bid': float(m.group(3))})

    def time_to_ms(t):
        h, m, s = t.split(':')
        s, ms = s.split(',')
        return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms)

    rows = []
    for c in chases:
        ct = time_to_ms(c['time'])
        p = c['price']

        best = None
        for pd in pdiffs:
            ref = pd['primary_ask'] if c['side'] == 'BUY' else pd['primary_bid']
            if abs(ref - p) <= threshold:
                if best is None or abs(time_to_ms(pd['time']) - ct) < abs(time_to_ms(best['time']) - ct):
                    best = pd

        if best:
            delay_ms = time_to_ms(best['time']) - ct
            matched = best['primary_ask'] if c['side'] == 'BUY' else best['primary_bid']
            price_seen_before = delay_ms <= 0
        else:
            delay_ms = None
            matched = None
            price_seen_before = None

        rows.append({
            'order_id':           c['order_id'],
            'chase_time':         c['time'],
            'side':               c['side'],
            'qty':                c['qty'],
            'chase_price':        p,
            'matched_pdiff_time': best['time'] if best else '',
            'delay_ms':           delay_ms if delay_ms is not None else '',
            'matched_price':      matched if matched is not None else '',
            'price_seen_before':  ('YES' if price_seen_before else 'NO') if price_seen_before is not None else '',
        })

    with open(out_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'order_id', 'chase_time', 'side', 'qty', 'chase_price',
            'matched_pdiff_time', 'delay_ms', 'matched_price', 'price_seen_before',
        ])
        writer.writeheader()
        writer.writerows(rows)

    seen_before = sum(1 for r in rows if r['price_seen_before'] == 'YES')
    not_seen    = sum(1 for r in rows if r['price_seen_before'] == 'NO')
    no_match    = sum(1 for r in rows if r['price_seen_before'] == '')
    delayed     = sum(1 for r in rows if isinstance(r['delay_ms'], int) and r['delay_ms'] > 500)

    print(f"Chase orders analysed : {len(rows)}")
    print(f"Price seen before      : {seen_before}  (delay <= 0)")
    print(f"Price seen after       : {not_seen}  (delay > 0)")
    print(f"  of which > 500ms    : {delayed}")
    print(f"No match in log        : {no_match}")
    print(f"Written to {out_csv}")


# ── Dispatch ──────────────────────────────────────────────────────────────────

COMMANDS = {
    '--chase-delay': {
        'usage': '<log_file> [out_csv]',
        'nargs': 1,
        'fn': lambda args: analyze_chase_delay(*args),
    },
}

if len(sys.argv) >= 2 and sys.argv[1] in COMMANDS:
    cmd = COMMANDS[sys.argv[1]]
    if len(sys.argv) < 2 + cmd['nargs']:
        print(f"Usage: python {sys.argv[0]} {sys.argv[1]} {cmd['usage']}")
        sys.exit(1)
    cmd['fn'](sys.argv[2:])
    sys.exit(0)

if len(sys.argv) < 2:
    print(f"Usage: python {sys.argv[0]} <log_file> [out_csv]")
    print(f"       python {sys.argv[0]} --chase-delay <log_file> [out_csv]")
    sys.exit(1)

analyze_orders(*sys.argv[1:])
