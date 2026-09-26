# MT5 API Bruno collection

In Bruno: **Open Collection** -> select this `bruno/` folder, pick the `local`
environment (top-right), then send a request, or right-click a folder -> **Run**
to execute everything with the built-in assertions.

- `validate_order/` - dry-run checks (`mt5.order_check`); never sends an order.
- `read_only/` - GET endpoints that don't change state.
- Order-placing / closing / withdraw endpoints are intentionally not included.

The API listens on port 5001 inside the `mt5` container and is not published to
the host by default. Publish it in `docker-compose.override.yml`
(`ports: ["5001:5001"]` under `mt5`) and use the `local` environment.

## validate_order response

Besides `ok`/`retcode`/`comment`/margin fields it returns:

- `checks[]` - `{name, ok, enforced, detail}` for terminal connection, algo trading,
  account permission, symbol trade mode, `tick_fresh` (market closed / stale feed),
  `spread_ok`, `order_book_liquidity`. `enforced: false` means informational only.
- `failed_checks[]` - names of enforced checks that failed (any one makes `ok` false).
- `market` - bid/ask, `tick_age_s`, `spread_points`, symbol volume min/max/step and
  a depth-of-market sample (`order_book`, `available: false` when the broker has none).

Tune with env vars on the `mt5` container: `MT5_MAX_TICK_AGE_S`, `MT5_SERVER_UTC_OFFSET_H`,
`MT5_MAX_SPREAD_POINTS`, `MT5_CHECK_ORDER_BOOK`, `MT5_ORDER_BOOK_WAIT_S` (see `.env.example`).
Note `01`/`02` return `ok: false` while the market is closed - that is now intended.
