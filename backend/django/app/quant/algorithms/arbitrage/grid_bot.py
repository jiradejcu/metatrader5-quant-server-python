import logging
import time
import threading
import os
from . import config
from decimal import Decimal
import json
from app.utils.redis_client import get_redis_connection
from app.connectors.binance.api.order import get_open_orders, cancel_all_open_orders, chase_order, new_order, get_latest_order_snapshot
from app.connectors.binance.api.ticker import get_ticker
from app.connectors.binance.api.position import get_position
from . import state

logger = logging.getLogger(__name__)

latest_grid_settings = None
latest_upper = None
latest_lower = None
boundary_price = 500.0
last_acted_order_id = None
optimistic_dirty_time = 0

OPEN_ORDER_STATUSES = ['NEW', 'PARTIALLY_FILLED']


def _parse_grid_settings(grid_dict):
    return {
        "upper": float(grid_dict.get('upper_diff', 0.0)),
        "lower": float(grid_dict.get('lower_diff', 0.0)),
        "max_position_size": float(grid_dict.get('max_position_size', 0.0)),
        "order_size": float(grid_dict.get('order_size', 0.0)),
    }


def _record_new_order(response):
    global optimistic_dirty_time, last_acted_order_id
    optimistic_dirty_time = time.time()
    if response and response.order_id:
        last_acted_order_id = response.order_id


def _execute_zone(entry_symbol, zone_side, chase_side, market_price, order_size,
                  open_price_order, pending_order_size, remaining_capacity,
                  allow_chase, can_open):
    if remaining_capacity < 0:
        logger.info(
            f"[Zone:{zone_side}] Capacity exceeded (remaining={remaining_capacity:.4f}) — cancelling all orders"
        )
        cancel_all_open_orders(entry_symbol)
    elif allow_chase:
        if open_price_order != round(market_price, 2) and pending_order_size > 0:
            logger.info(
                f"[Zone:{zone_side}] Chasing order: open_price={open_price_order:.2f} → market={market_price:.2f}, "
                f"size={pending_order_size}"
            )
            chase_order(entry_symbol, pending_order_size, chase_side)
        else:
            logger.debug(
                f"[Zone:{zone_side}] Chase skipped: price aligned "
                f"(open={open_price_order:.2f}, market={round(market_price, 2):.2f}) or no pending qty"
            )
    elif can_open:
        price = market_price + boundary_price if zone_side == 'SELL' else market_price - boundary_price
        logger.info(f"[Zone:{zone_side}] Placing new order @ {price:.2f}, size={order_size}")
        _record_new_order(new_order(entry_symbol, float(order_size), price, zone_side))
    else:
        logger.debug(
            f"[Zone:{zone_side}] No action "
            f"(allow_chase={allow_chase}, can_open={can_open}, capacity={remaining_capacity:.4f})"
        )


def _process_tick(entry_symbol, order_snapshot, contract_size, minimum_trade_amount,
                  upper_limit, lower_limit, max_pos, order_size,
                  current_upper_diff, current_lower_diff):
    """Execute one trading decision from a pubsub tick."""
    global optimistic_dirty_time

    open_orders = get_open_orders(entry_symbol)
    ticker = get_ticker(entry_symbol)
    positions = get_position(entry_symbol)

    best_bid = float(ticker.get('best_bid', 0))
    best_ask = float(ticker.get('best_ask', 0))
    position_amt = float(positions.get('positionAmt', '0'))
    abs_position_amt = abs(position_amt)

    logger.debug(
        f"[Tick] bid={best_bid:.2f} ask={best_ask:.2f} pos={position_amt} "
        f"open_orders={len(open_orders or [])} "
        f"upper_diff={current_upper_diff:.2f} lower_diff={current_lower_diff:.2f}"
    )

    first_order = open_orders[0] if open_orders else None
    open_price_order = round(float(getattr(first_order, 'price', 0)), 2) if first_order else 0.0
    pending_order_size = float(getattr(first_order, 'orig_qty', 0)) if first_order else 0.0

    buy_pending = sum(float(getattr(o, 'orig_qty', 0)) for o in open_orders if getattr(o, 'side', '') == 'BUY')
    sell_pending = sum(float(getattr(o, 'orig_qty', 0)) for o in open_orders if getattr(o, 'side', '') == 'SELL')
    net_pending = buy_pending - sell_pending

    remaining_capacity = max_pos - abs(position_amt + net_pending)
    can_open_orders = remaining_capacity > 0
    allow_chase_by_status = remaining_capacity >= 0 and order_snapshot['status'] in OPEN_ORDER_STATUSES

    logger.debug(
        f"[Tick] net_pending={net_pending} remaining_capacity={remaining_capacity:.4f} "
        f"can_open={can_open_orders} allow_chase={allow_chase_by_status} "
        f"snapshot_status={order_snapshot['status']} snapshot_side={order_snapshot['side']}"
    )

    unfilled_position = ((Decimal(str(abs_position_amt)) * minimum_trade_amount) * contract_size) % contract_size
    order_aligns_with_position = (
        (order_snapshot['side'] == 'BUY' and position_amt > 0) or
        (order_snapshot['side'] == 'SELL' and position_amt < 0)
    )
    fraction_adjustment = (contract_size - unfilled_position) if order_aligns_with_position else unfilled_position
    fraction_size = (fraction_adjustment / contract_size) * minimum_trade_amount if order_size > 0 else 0
    has_fractional_position = unfilled_position != 0

    if has_fractional_position:
        side = order_snapshot['side']
        optimal_price = best_bid - boundary_price if side == 'BUY' else best_ask + boundary_price
        logger.info(
            f"[Tick] Fractional position: unfilled={unfilled_position} fraction_size={fraction_size:.4f} "
            f"side={side} optimal_price={optimal_price:.2f} aligns_with_pos={order_aligns_with_position}"
        )
        if remaining_capacity < 0:
            logger.info(f"[Tick] Fractional: capacity exceeded — cancelling all orders")
            cancel_all_open_orders(entry_symbol)
        if allow_chase_by_status:
            logger.info(f"[Tick] Fractional: chasing {side} order, size={fraction_size:.4f}")
            chase_order(entry_symbol, fraction_size, side)
            optimistic_dirty_time = time.time()
        elif can_open_orders:
            logger.info(f"[Tick] Fractional: placing new {side} @ {optimal_price:.2f}, size={fraction_size:.4f}")
            _record_new_order(new_order(entry_symbol, fraction_size, optimal_price, side))
        else:
            logger.debug(
                f"[Tick] Fractional: no action "
                f"(allow_chase={allow_chase_by_status}, can_open={can_open_orders})"
            )
    else:
        logger.debug(
            f"[Tick] Zone check: upper_diff={current_upper_diff:.2f} (limit={upper_limit:.2f}), "
            f"lower_diff={current_lower_diff:.2f} (limit={lower_limit:.2f})"
        )
        side = order_snapshot['side']
        if current_upper_diff >= upper_limit:
            logger.info(f"[Tick] SELL zone triggered: upper_diff={current_upper_diff:.2f} >= {upper_limit:.2f}")
            _execute_zone(entry_symbol, 'SELL', side, best_ask, order_size,
                          open_price_order, pending_order_size, remaining_capacity,
                          allow_chase_by_status, can_open_orders)
        elif current_lower_diff <= lower_limit:
            logger.info(f"[Tick] BUY zone triggered: lower_diff={current_lower_diff:.2f} <= {lower_limit:.2f}")
            _execute_zone(entry_symbol, 'BUY', side, best_bid, order_size,
                          open_price_order, pending_order_size, remaining_capacity,
                          allow_chase_by_status, can_open_orders)
        else:
            logger.debug(f"[Tick] No zone triggered: within range")


def poll_order_state(entry_symbol):
    logger.info(f"[Poller Order Status Thread] Starting Background Poller for {entry_symbol}")
    while True:
        start_time = time.time()
        try:
            snapshot = get_latest_order_snapshot(entry_symbol)
            all_orders = get_open_orders(entry_symbol)
            logger.debug(f"all_orders: {len(all_orders)}")

            data = snapshot or {}
            with state.state_lock:
                state.placing_order_state.update({
                    "order_id": data.get('order_id'),
                    "status": data.get('status'),
                    "fill_pct": data.get('fill_pct', 0),
                    "side": data.get('side'),
                    "is_clean": data.get('is_clean', True),
                    "price": data.get('price'),
                    "orig_qty": data.get('orig_qty', 0),
                    "total_orders": len(all_orders) if all_orders else 0,
                })
        except Exception as e:
            logger.error(f"Poller Thread Error: {e}")
            time.sleep(1)

        # 500ms ≈ 120 calls/min, well under the 2,400/min limit
        elapsed = time.time() - start_time
        time.sleep(max(0.01, 0.5 - elapsed))


def get_pause_status():
    return get_redis_connection().get("grid_bot_paused_flag")


def handle_grid_flow(pubsub, price_diff_key, grid_range_key):
    global latest_grid_settings, latest_upper, latest_lower
    global last_acted_order_id, optimistic_dirty_time
    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    CONTRACT_SIZE = config.PAIRS[PAIR_INDEX]['contract_size']
    MINIMUM_TRADE_AMOUNT = config.PAIRS[PAIR_INDEX]['minimum_trade_amount']
    entry_symbol = config.PAIRS[PAIR_INDEX]['entry']['symbol']

    # --- Initial Fetch for Grid Settings ---
    try:
        redis_conn = get_redis_connection()
        initial_grid_data = redis_conn.get(grid_range_key)
        if initial_grid_data:
            latest_grid_settings = _parse_grid_settings(json.loads(initial_grid_data))
            logger.info(f"Initial grid settings loaded: {latest_grid_settings}")
    except Exception as e:
        logger.error(f"Failed to fetch initial grid settings: {e}")

    # --- Start Pub/Sub Loop ---
    while True:
        try:
            for message in pubsub.listen():
                if message['type'] != 'message':
                    continue

                now = time.time()
                with state.state_lock:
                    # LATENCY GUARD: wait 500ms after sending an order
                    if now - optimistic_dirty_time < 0.5:
                        logger.debug(
                            f"[Guard] Latency guard active: "
                            f"{now - optimistic_dirty_time:.3f}s since last order — skipping tick"
                        )
                        continue
                    order_snapshot = state.placing_order_state.copy()

                # STALE DATA GUARD: skip if poller still shows the old order_id
                if last_acted_order_id and order_snapshot.get('order_id') == last_acted_order_id:
                    if order_snapshot.get('status') not in ['FILLED', 'CANCELED', 'EXPIRED']:
                        logger.debug(
                            f"[Guard] Stale data: order {last_acted_order_id} "
                            f"still {order_snapshot.get('status')} — skipping tick"
                        )
                        continue

                channel = message['channel'].decode('utf-8')
                data_payload = message['data']

                if channel == price_diff_key:
                    price_dict = json.loads(data_payload) if data_payload else {}
                    latest_upper = round(float(price_dict.get('current_upper_diff', "0")), 2)
                    latest_lower = round(float(price_dict.get('current_lower_diff', "0")), 2)
                    logger.debug(f"[PubSub] Price diff updated: upper={latest_upper:.2f}, lower={latest_lower:.2f}")
                elif channel == grid_range_key:
                    latest_grid_settings = _parse_grid_settings(json.loads(data_payload) if data_payload else {})
                    logger.info(f"[PubSub] Grid settings updated: {latest_grid_settings}")

                paused = get_pause_status()
                allow_place_orders = (
                    latest_grid_settings is not None
                    and latest_upper is not None
                    and latest_lower is not None
                    and not paused
                )

                if not allow_place_orders:
                    logger.debug(
                        f"[Grid] Orders blocked: "
                        f"has_settings={latest_grid_settings is not None} "
                        f"has_price_diff={latest_upper is not None and latest_lower is not None} "
                        f"paused={bool(paused)}"
                    )

                # TRADING LOGIC
                if allow_place_orders:
                    if order_snapshot.get('total_orders') > 1:
                        logger.info(
                            f"[Grid] Multiple open orders ({order_snapshot['total_orders']}) — cancelling all"
                        )
                        cancel_all_open_orders(entry_symbol)

                    try:
                        with state.state_lock:
                            # Mark dirty immediately so the poller sees it before we call Binance
                            state.placing_order_state["is_clean"] = False

                        upper = latest_grid_settings['upper']
                        lower = latest_grid_settings['lower']
                        max_pos = latest_grid_settings['max_position_size']
                        order_size = latest_grid_settings['order_size']

                        _process_tick(
                            entry_symbol, order_snapshot,
                            CONTRACT_SIZE, MINIMUM_TRADE_AMOUNT,
                            upper, lower, max_pos, order_size,
                            latest_upper, latest_lower,
                        )

                    except Exception as e:
                        logger.error(f"[Placing Bot Thread] Error in processing grid flow logic: {e}", exc_info=True)
                        with state.state_lock:
                            state.placing_order_state["is_clean"] = True
                        time.sleep(1)

                time.sleep(0.25)
        except Exception as e:
            logger.error(f"[Placing Bot Thread] Critical PubSub failure: {e}. Reconnecting in 1s...", exc_info=True)
            time.sleep(1)


def start_grid_bot_sync():
    if os.environ.get('RUN_MAIN') != 'true':
        return

    try:
        PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
        entry_exchange = config.PAIRS[PAIR_INDEX]['entry']['exchange']
        entry_symbol = config.PAIRS[PAIR_INDEX]['entry']['symbol']
        hedge_symbol = config.PAIRS[PAIR_INDEX]['hedge']['symbol']
        logger.info(f"Starting grid trading process for {entry_symbol} ...")

        redis_conn = get_redis_connection()
        pubsub = redis_conn.pubsub()

        price_diff = f"spread:{entry_exchange}:{entry_symbol}"
        grid_range = f"setting_grid_channel:{entry_symbol}:{hedge_symbol}"
        pubsub.subscribe(price_diff, grid_range)
        logger.info(f"Grid bot subscribed to channels: [{price_diff}], [{grid_range}].")

        threading.Thread(
            target=handle_grid_flow,
            args=(pubsub, price_diff, grid_range), daemon=True
        ).start()
        threading.Thread(
            target=poll_order_state,
            args=(entry_symbol,), daemon=True
        ).start()
        logger.info("Grid Bot thread started and running in background.")
    except Exception as e:
        logger.error(f"Error while syncing grid montinor: {e}", exc_info=True)
