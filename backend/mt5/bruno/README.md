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
