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
    r"side=(\w+) fill_price=([0-9.]+) avg_price=[0-9.]+ qty=[0-9.]+/[0-9.]+ order_id=(\d+)"
)
# MT5 new hedge (action=1): price is request[5]
hedge_new_pat = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+).*Order successful:.*?"
    r"'request': \[1, \d+, \d+, '\S+', ([0-9.]+), ([0-9.]+),"
)


# ── Functions ─────────────────────────────────────────────────────────────────

def analyze_orders(log_file, out_csv=None):
    import os
    if out_csv is None:
        base = os.path.splitext(os.path.basename(log_file))[0]
        out_csv = os.path.join(os.path.dirname(os.path.abspath(log_file)), f"{base}_orders.csv")

    price_diffs = []
    fills = []
    hedges_new = []

    with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            m = price_diff_pat.search(line)
            if m:
                price_diffs.append({
                    'ts_str': m.group(1), 'ts_dt': datetime.strptime(m.group(1), ts_fmt),
                    'ask_diff': float(m.group(2)), 'bid_diff': float(m.group(3)),
                    'primary_ask': float(m.group(4)), 'hedge_ask': float(m.group(5)),
                    'primary_bid': float(m.group(6)), 'hedge_bid': float(m.group(7)),
                })
                continue
            m = filled_pat.search(line)
            if m:
                fills.append({
                    'ts_str': m.group(1), 'ts_dt': datetime.strptime(m.group(1), ts_fmt),
                    'side': m.group(2), 'fill_price': float(m.group(3)), 'order_id': m.group(4)
                })
                continue
            m = hedge_new_pat.search(line)
            if m:
                hedges_new.append({
                    'ts_str': m.group(1), 'ts_dt': datetime.strptime(m.group(1), ts_fmt),
                    'volume': float(m.group(2)), 'price': float(m.group(3)),
                    'used': False
                })

    print(f"Price diffs   : {len(price_diffs)}")
    print(f"Entry fills   : {len(fills)}")
    print(f"MT5 new hedges: {len(hedges_new)}")
    print()

    results = []

    for fill in fills:
        ft = fill['ts_dt']

        # Last price diff strictly before fill
        pred = None
        for pd in reversed(price_diffs):
            if pd['ts_dt'] <= ft:
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
        hedge_price_diff   = round(actual_hedge_price - pred_hedge_price, 4)
        slippage           = round(actual_price_diff - predicted_price_diff, 4)

        results.append({
            'fill_ts'              : fill['ts_str'],
            'side'                 : fill['side'],
            'order_id'             : fill['order_id'],
            'pred_ts'              : pred['ts_str'],
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
            'match'                : True
        })

    matched   = [r for r in results if r['match']]
    unmatched = [r for r in results if not r['match']]

    with open(out_csv, 'w', newline='') as f:
        fieldnames = [
            'fill_ts', 'side', 'order_id', 'pred_ts',
            'pred_primary_price', 'pred_hedge_price', 'predicted_price_diff',
            'hedge_ts', 'actual_primary_price', 'actual_hedge_price', 'actual_price_diff',
            'primary_price_diff', 'hedge_price_diff', 'slippage',
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(matched)
    print(f"Written to {out_csv}")
    print()

    col = (
        f"{'#':<3} {'Fill Time':<26} {'S':<5} {'Order ID':<14}"
        f"{'PredPrimary':>11} {'PredHedge':>10} {'PredDiff':>9}"
        f"{'ActPrimary':>11} {'ActHedge':>10} {'ActDiff':>9}"
        f"{'PrimaryDiff':>12} {'HedgeDiff':>10} {'Slippage':>9}"
    )
    print(col)
    print("-" * len(col))

    for i, r in enumerate(matched, 1):
        s = f"{r['slippage']:+.4f}"
        print(
            f"{i:<3} {r['fill_ts']:<26} {r['side']:<5} {r['order_id']:<14}"
            f"{r['pred_primary_price']:>11.2f} {r['pred_hedge_price']:>10.2f} {r['predicted_price_diff']:>9.2f}"
            f"{r['actual_primary_price']:>11.2f} {r['actual_hedge_price']:>10.2f} {r['actual_price_diff']:>9.4f}"
            f"{r['primary_price_diff']:>+12.4f} {r['hedge_price_diff']:>+10.4f} {s:>9}"
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
        worse  = sum(1 for r in matched if (r['side'] == 'SELL' and r['slippage'] < 0) or (r['side'] == 'BUY' and r['slippage'] > 0))
        better = sum(1 for r in matched if (r['side'] == 'SELL' and r['slippage'] > 0) or (r['side'] == 'BUY' and r['slippage'] < 0))
        print(f"  Worse than pred: {worse}  |  Better: {better}")
        print(sep)

    if unmatched:
        print(f"\nUnmatched fills ({len(unmatched)}):")
        for r in unmatched:
            f_ = r['fill']
            print(f"  {f_['ts_str']} side={f_['side']} fill={f_['fill_price']}"
                  f"  pred={'YES' if r['pred'] else 'NO'} hedge={'YES' if r['hedge'] else 'NO'}")


def analyze_chase_delay(log_file, out_csv=None, symbol='XAUUSDT', threshold=0.10):
    if out_csv is None:
        import os
        base = os.path.splitext(os.path.basename(log_file))[0]
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
