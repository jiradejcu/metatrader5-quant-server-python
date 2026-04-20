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
has_running_placing_bot = False  # reservation ticket: only one placing cycle runs at a time
last_acted_order_id = None
optimistic_dirty_time = 0

OPEN_ORDER_STATUSES = ['NEW', 'PARTIALLY_FILLED']


def _parse_grid_settings(grid_dict):
    return {
        "upper": float(grid_dict.get('upper_diff', 0.0)),
        "lower": float(grid_dict.get('lower_diff', 0.0)),
        "max_position_size": float(grid_dict.get('max_position_size', 0.0)),
        "order_size": float(grid_dict.get('order_size', 0.0)),
        "close_long": float(grid_dict.get('close_long', 0.0)),
        "close_short": float(grid_dict.get('close_short', 0.0)),
    }


def _record_new_order(response):
    global optimistic_dirty_time, last_acted_order_id
    optimistic_dirty_time = time.time()
    if response and response.order_id:
        last_acted_order_id = response.order_id


def _execute_zone(entry_symbol, zone_side, chase_side, market_price, order_size,
                  open_price_order, pending_order_size, remaining_capacity,
                  allow_chase, can_open):
    if allow_chase:
        if remaining_capacity < 0:
            cancel_all_open_orders(entry_symbol)
        elif open_price_order != round(market_price, 2) and pending_order_size > 0:
            chase_order(entry_symbol, pending_order_size, chase_side)
    elif can_open:
        price = market_price + boundary_price if zone_side == 'SELL' else market_price - boundary_price
        _record_new_order(new_order(entry_symbol, float(order_size), price, zone_side))


def poller_snapshot_io_for_placing_bot(entry_symbol):
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
    global latest_grid_settings, has_running_placing_bot, latest_upper, latest_lower
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
                    if now - optimistic_dirty_time < 0.5 or has_running_placing_bot:
                        continue
                    order_snapshot = state.placing_order_state.copy()

                # STALE DATA GUARD: skip if poller still shows the old order_id
                if last_acted_order_id and order_snapshot.get('order_id') == last_acted_order_id:
                    if order_snapshot.get('status') not in ['FILLED', 'CANCELED', 'EXPIRED']:
                        continue

                channel = message['channel'].decode('utf-8')
                data_payload = message['data']

                if channel == price_diff_key:
                    price_dict = json.loads(data_payload) if data_payload else {}
                    latest_upper = round(float(price_dict.get('current_upper_diff', "0")), 2)
                    latest_lower = round(float(price_dict.get('current_lower_diff', "0")), 2)
                elif channel == grid_range_key:
                    latest_grid_settings = _parse_grid_settings(json.loads(data_payload) if data_payload else {})

                if order_snapshot.get('total_orders') > 1:
                    cancel_all_open_orders(entry_symbol)

                allow_place_orders = (
                    latest_grid_settings is not None
                    and latest_upper is not None
                    and latest_lower is not None
                    and not get_pause_status()
                )

                # TRADING LOGIC
                if allow_place_orders:
                    try:
                        with state.state_lock:
                            has_running_placing_bot = True
                            # Mark dirty immediately so other threads see it before we call Binance
                            state.placing_order_state["is_clean"] = False

                        upper = latest_grid_settings['upper']
                        lower = latest_grid_settings['lower']
                        max_pos = latest_grid_settings['max_position_size']
                        order_size = latest_grid_settings['order_size']

                        # Get current status from Binance (Network I/O)
                        open_orders = get_open_orders(entry_symbol)
                        ticker = get_ticker(entry_symbol)
                        positions = get_position(entry_symbol)
                        best_bid = float(ticker.get('best_bid', 0))
                        best_ask = float(ticker.get('best_ask', 0))
                        position_amt = float(positions.get('positionAmt', '0'))
                        abs_position_amt = abs(position_amt)
                        side_position = 'BUY' if position_amt > 0 else ('SELL' if position_amt < 0 else None)

                        open_price_order = round(float(getattr(open_orders[0], 'price', 0)), 2) if open_orders else 0.0
                        pending_order_size = sum(float(getattr(o, 'orig_qty', 0)) for o in open_orders)

                        # When user opens a reverse order, pending size works against current position
                        if side_position != order_snapshot['side'] and side_position is not None:
                            pending_order_size *= -1

                        remaining_capacity = max_pos - (abs_position_amt + pending_order_size)
                        can_open_orders = remaining_capacity > 0
                        allow_chase_by_status = remaining_capacity >= 0 and order_snapshot['status'] in OPEN_ORDER_STATUSES

                        unfilled_position = ((Decimal(str(abs_position_amt)) * MINIMUM_TRADE_AMOUNT) * CONTRACT_SIZE) % CONTRACT_SIZE
                        order_aligns_with_position = (
                            (order_snapshot['side'] == 'BUY' and position_amt > 0) or
                            (order_snapshot['side'] == 'SELL' and position_amt < 0)
                        )
                        fraction_adjustment = (CONTRACT_SIZE - unfilled_position) if order_aligns_with_position else unfilled_position
                        fraction_size = (fraction_adjustment / CONTRACT_SIZE) * MINIMUM_TRADE_AMOUNT if order_size > 0 else 0
                        has_fractional_position = unfilled_position != 0

                        if has_fractional_position:
                            if remaining_capacity < 0:
                                cancel_all_open_orders(entry_symbol)
                            side = order_snapshot['side']
                            optimal_price = best_bid - boundary_price if side == 'BUY' else best_ask + boundary_price
                            if allow_chase_by_status:
                                chase_order(entry_symbol, fraction_size, side)
                                optimistic_dirty_time = time.time()
                            elif can_open_orders:
                                _record_new_order(new_order(entry_symbol, fraction_size, optimal_price, side))
                        else:
                            side = order_snapshot['side']
                            if latest_upper >= upper:
                                _execute_zone(entry_symbol, 'SELL', side, best_ask, order_size,
                                              open_price_order, pending_order_size, remaining_capacity,
                                              allow_chase_by_status, can_open_orders)
                            elif latest_lower <= lower:
                                _execute_zone(entry_symbol, 'BUY', side, best_bid, order_size,
                                              open_price_order, pending_order_size, remaining_capacity,
                                              allow_chase_by_status, can_open_orders)

                    except Exception as e:
                        logger.error(f"[Placing Bot Thread] Error in processing grid flow logic: {e}", exc_info=True)
                        with state.state_lock:
                            state.placing_order_state["is_clean"] = True
                        time.sleep(1)

                has_running_placing_bot = False
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
            target=poller_snapshot_io_for_placing_bot,
            args=(entry_symbol,), daemon=True
        ).start()
        logger.info("Grid Bot thread started and running in background.")
    except Exception as e:
        logger.error(f"Error while syncing grid montinor: {e}", exc_info=True)
