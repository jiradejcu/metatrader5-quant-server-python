import logging
import time
import threading
import os
from . import config
from decimal import Decimal
import json
from app.utils.redis_client import get_redis_connection
from app.connectors.binance.api.order import get_open_orders, cancel_all_open_orders, chase_order, get_latest_order_snapshot
from app.connectors.binance.api.position import get_position
from . import state

logger = logging.getLogger(__name__)

latest_grid_settings = None
latest_upper = None
latest_lower = None
last_acted_order_id = None
last_handled_fill_order_id = None
optimistic_dirty_time = 0


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


def _determine_zone(current_upper_diff, current_lower_diff, upper_limit, lower_limit):
    if current_upper_diff >= upper_limit:
        return 'SELL'
    if current_lower_diff <= lower_limit:
        return 'BUY'
    return 'NEUTRAL'


def _compute_target(zone, order_snapshot, order_size, remaining_capacity):
    """Return (side, size) for the desired open limit order, or None if no order needed."""
    if remaining_capacity <= 0:
        logger.info(f"[Target] Capacity exhausted (remaining={remaining_capacity:.4f}) → None")
        return None

    if zone == 'SELL':
        return ('SELL', order_size)
    if zone == 'BUY':
        return ('BUY', order_size)

    # NEUTRAL: place hedge if the last order filled and we have not acted on it yet
    filled_id = order_snapshot.get('order_id')
    filled_side = order_snapshot.get('side')
    if (order_snapshot.get('status') == 'FILLED'
            and filled_side is not None
            and filled_id != last_handled_fill_order_id):
        opposite = 'BUY' if filled_side == 'SELL' else 'SELL'
        logger.info(f"[Target] Neutral: {filled_side} filled → hedge {opposite}")
        return (opposite, order_size)

    return None


def _reconcile(entry_symbol, target, open_orders):
    """Take the minimal action to move current open orders to the target state."""
    global optimistic_dirty_time

    if target is None:
        if open_orders:
            logger.info(f"[Reconcile] Target=None: cancelling {len(open_orders)} open order(s)")
            cancel_all_open_orders(entry_symbol)
        else:
            logger.debug("[Reconcile] Target=None: no open orders — nothing to do")
        return

    target_side, target_size = target

    if not open_orders:
        logger.info(f"[Reconcile] No open order → chasing {target_side}, size={target_size}")
        _record_new_order(chase_order(entry_symbol, float(target_size), target_side))
        return

    first = open_orders[0]
    current_side = getattr(first, 'side', None)
    current_size = float(getattr(first, 'orig_qty', 0))

    if current_side != target_side:
        logger.info(
            f"[Reconcile] Wrong side ({current_side} vs target {target_side}) — cancelling, will re-place next tick"
        )
        cancel_all_open_orders(entry_symbol)
        return

    logger.debug(f"[Reconcile] Chasing {target_side}, size={current_size}")
    chase_order(entry_symbol, current_size, target_side)
    optimistic_dirty_time = time.time()


def _process_tick(entry_symbol, order_snapshot, contract_size, minimum_trade_amount,
                  upper_limit, lower_limit, max_pos, order_size,
                  current_upper_diff, current_lower_diff):
    """Execute one trading decision from a pubsub tick."""
    global optimistic_dirty_time, last_handled_fill_order_id

    open_orders = get_open_orders(entry_symbol)
    positions = get_position(entry_symbol)

    position_amt = float(positions.get('positionAmt', '0'))
    abs_position_amt = abs(position_amt)

    logger.debug(
        f"pos={position_amt} "
        f"open_orders={len(open_orders or [])} "
        f"upper_diff={current_upper_diff:.2f} lower_diff={current_lower_diff:.2f}"
    )

    buy_pending = sum(float(getattr(o, 'orig_qty', 0)) for o in open_orders if getattr(o, 'side', '') == 'BUY')
    sell_pending = sum(float(getattr(o, 'orig_qty', 0)) for o in open_orders if getattr(o, 'side', '') == 'SELL')
    net_pending = buy_pending - sell_pending
    remaining_capacity = max_pos - abs(position_amt + net_pending)

    logger.debug(
        f"net_pending={net_pending} remaining_capacity={remaining_capacity:.4f} "
        f"snapshot_status={order_snapshot['status']} snapshot_side={order_snapshot['side']}"
    )

    # --- Fractional position: lot-size alignment edge case ---
    unfilled_position = ((Decimal(str(abs_position_amt)) * minimum_trade_amount) * contract_size) % contract_size
    if unfilled_position != 0:
        order_aligns_with_position = (
            (order_snapshot['side'] == 'BUY' and position_amt > 0) or
            (order_snapshot['side'] == 'SELL' and position_amt < 0)
        )
        fraction_adjustment = (contract_size - unfilled_position) if order_aligns_with_position else unfilled_position
        fraction_size = (fraction_adjustment / contract_size) * minimum_trade_amount if order_size > 0 else 0
        side = order_snapshot['side']
        if side is None:
            logger.warning("Fractional: skipping — order_snapshot side is None")
            return
        logger.info(
            f"Fractional position: unfilled={unfilled_position} fraction_size={fraction_size:.4f} "
            f"side={side} aligns_with_pos={order_aligns_with_position}"
        )
        if remaining_capacity < 0:
            logger.info(f"Fractional: capacity exceeded — cancelling all orders")
            cancel_all_open_orders(entry_symbol)
            return
        logger.info(f"Fractional: chasing {side} order, size={fraction_size:.4f}")
        chase_order(entry_symbol, fraction_size, side)
        optimistic_dirty_time = time.time()
        return

    # --- Normal grid logic: zone → target → reconcile ---
    if len(open_orders) > 1:
        logger.info(f"Multiple open orders ({len(open_orders)}) — cancelling all before reconcile")
        cancel_all_open_orders(entry_symbol)
        return

    zone = _determine_zone(current_upper_diff, current_lower_diff, upper_limit, lower_limit)
    logger.debug(
        f"Zone={zone}: upper_diff={current_upper_diff:.2f} (limit={upper_limit:.2f}), "
        f"lower_diff={current_lower_diff:.2f} (limit={lower_limit:.2f})"
    )

    target = _compute_target(zone, order_snapshot, order_size, remaining_capacity)
    logger.debug(f"Target={target}")

    if zone == 'NEUTRAL' and target is not None:
        last_handled_fill_order_id = order_snapshot.get('order_id')

    _reconcile(entry_symbol, target, open_orders)

    if zone == 'NEUTRAL' and target is not None and last_acted_order_id:
        last_handled_fill_order_id = last_acted_order_id


def poll_order_state(entry_symbol):
    logger.info(f"Starting Background Polling for {entry_symbol}")
    while True:
        start_time = time.time()
        try:
            snapshot = get_latest_order_snapshot(entry_symbol)
            open_orders = get_open_orders(entry_symbol)
            logger.debug(f"Open order count: {len(open_orders)}")

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
                    "total_orders": len(open_orders) if open_orders else 0,
                })
        except Exception as e:
            logger.error(f"Thread Error: {e}")
            time.sleep(1)

        # 500ms ≈ 120 calls/min, well under the 2,400/min limit
        elapsed = time.time() - start_time
        time.sleep(max(0.1, 0.5 - elapsed))


def get_pause_status():
    return get_redis_connection().get("grid_bot_paused_flag")


def handle_grid_flow(pubsub, price_diff_key, grid_range_key):
    global latest_grid_settings, latest_upper, latest_lower
    global last_acted_order_id, last_handled_fill_order_id, optimistic_dirty_time
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

                time.sleep(0.1)
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
