import logging
import time
import threading
import os
from . import config
from decimal import Decimal
import json
import os
from app.utils.redis_client import get_redis_connection
from app.connectors.binance.api.order import get_open_orders, cancel_all_open_orders, chase_order, new_order, get_latest_order_snapshot
from app.connectors.binance.api.ticker import get_ticker
from app.connectors.binance.api.position import get_position
from . import state

logger = logging.getLogger(__name__)

# For securing uses global from many threads
latest_update = None
latest_grid_settings = None
latest_upper = None
latest_lower = None
boundary_price = 500.0
has_running_placing_bot = False # working as reservation ticket (Queue concept - allow one queue works and others will reject if first queue does not finish work)
last_acted_order_id = None
optimistic_dirty_time = 0

def poller_snapshot_io_for_placing_bot(entry_symbol):
    logger.info(f"[Poller Order Status Thread] Starting Background Poller for {entry_symbol}")
    while True:
        start_time = time.time() # Capture start time
        try:
            snapshot = get_latest_order_snapshot(entry_symbol)
            all_orders = get_open_orders(entry_symbol)

            # logger.debug(f"all_orders: {len(all_orders)}")
            
            with state.state_lock:
                state.placing_order_state["order_id"] = snapshot.get('order_id', None) if snapshot else None
                state.placing_order_state["status"] = snapshot.get('status', None) if snapshot else None
                state.placing_order_state["fill_pct"] = snapshot.get('fill_pct', 0) if snapshot else 0
                state.placing_order_state["side"] = snapshot.get('side', None) if snapshot else None
                state.placing_order_state["is_clean"] = snapshot.get('is_clean', True) if snapshot else True
                state.placing_order_state["price"] = snapshot.get('price', None) if snapshot else None
                state.placing_order_state["orig_qty"] = snapshot.get('orig_qty', 0) if snapshot else 0
                state.placing_order_state["total_orders"] = len(all_orders) if all_orders else 0
        except Exception as e:
            logger.error(f"Poller Thread Error: {e}")
            time.sleep(1) # Wait longer on error

        # 500 ms = ~ 120 calls per minute. 
        # Well under the 2,400 per minute limit.    
        elapsed = time.time() - start_time
        sleep_time = max(0.01, 0.5 - elapsed) 
        time.sleep(sleep_time)

def get_pause_status():
    redis_conn = get_redis_connection()
    redis_key= "grid_bot_paused_flag"
    is_paused = redis_conn.get(redis_key)
    return is_paused

def handle_grid_flow(pubsub, price_diff_key, grid_range_key):
    global latest_update, latest_grid_settings, has_running_placing_bot, latest_upper, latest_lower
    global last_acted_order_id, optimistic_dirty_time
    global order_snapshot
    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    CONTRACT_SIZE = int(os.getenv('CONTRACT_SIZE'))
    MINIMUM_TRADE_AMOUNT = int(os.getenv('MINIMUM_TRADE_AMOUNT'))
    entry_symbol = config.PAIRS[PAIR_INDEX]['entry']['symbol']

    # --- Initial Fetch for Grid Settings ---
    try:
        redis_conn = get_redis_connection()
        initial_grid_data = redis_conn.get(grid_range_key)
        if initial_grid_data:
            grid_dict = json.loads(initial_grid_data)

            latest_grid_settings = {
                "upper": float(grid_dict.get('upper_diff', 0.0)),
                "lower": float(grid_dict.get('lower_diff', 0.0)),
                "max_position_size": float(grid_dict.get('max_position_size', 0.0)),
                "order_size": float(grid_dict.get('order_size', 0.0)),
                "close_long": float(grid_dict.get('close_long', 0.0)),
                "close_short": float(grid_dict.get('close_short', 0.0)),
            }
            logger.info(f"Initial grid settings loaded: {latest_grid_settings}")
    except Exception as e:
        logger.error(f"Failed to fetch initial grid settings: {e}")

    # --- Start Pub/Sub Loop ---
    while True:
        try:
            for message in pubsub.listen():
                # Only process messages of type 'message' to avoid subscription confirmations and other types
                if message['type'] != 'message':
                    continue

                now = time.time()
                with state.state_lock:
                    # LATENCY GUARD: wait 500ms after sending a order
                    if (now - optimistic_dirty_time < 0.5 or 
                        has_running_placing_bot):
                        continue

                    order_snapshot = state.placing_order_state.copy()


                # STALE DATA GUARD:
                # If the poller is still showing the OLD order_id we just finished, skip.
                if last_acted_order_id and order_snapshot.get('order_id') == last_acted_order_id:
                    if order_snapshot.get('status') not in ['FILLED', 'CANCELED', 'EXPIRED']:
                        # logger.debug('[STALE DATA GUARD]: skip on going order!!')
                        continue
                
                channel = message['channel'].decode('utf-8')
                data_payload = message['data']
                allow_place_orders = False

                # order_snapshot = get_latest_order_snapshot(symbol)
                # logger.debug(f'[Placing Bot Thread | Before running algorithm] has_running_placing_bot: {has_running_placing_bot}')
                # logger.debug(f'[Placing Bot Thread | Before running algorithm] grid_bot order_snapshot: {order_snapshot} and allow_place_orders: {allow_place_orders}')

                if channel == price_diff_key:
                    price_dict = json.loads(data_payload) if data_payload else {}
                    latest_upper = round(float(price_dict.get('current_upper_diff', "0")), 2)
                    latest_lower = round(float(price_dict.get('current_lower_diff', "0")), 2)
                    
                elif channel == grid_range_key:
                    grid_dict = json.loads(data_payload) if data_payload else {}
                    latest_grid_settings = {
                        "upper": float(grid_dict.get('upper_diff', 0.0)),
                        "lower": float(grid_dict.get('lower_diff', 0.0)),
                        "max_position_size": float(grid_dict.get('max_position_size', 0.0)),
                        "order_size": float(grid_dict.get('order_size', 0.0)),
                        "close_long": float(grid_dict.get('close_long', 0.0)),
                        "close_short": float(grid_dict.get('close_short', 0.0)),
                    }
                
                is_paused = get_pause_status()

                # Audit metrics for enabling informed decision in placing orders
                # logger.debug(f"[Placing Bot Thread | Before running algorithm] Latest upper diff: {latest_upper}, Latest lower diff: {latest_lower}, Is paused: {is_paused}")
                # logger.debug(f"[Placing Bot Thread | Before running algorithm] latest_grid_settings: {latest_grid_settings}")
                # logger.debug(f"[Placing Bot Thread | Before running algorithm] is allow to place order logic run: {latest_grid_settings and latest_upper is not None and latest_lower is not None and not is_paused}")

                # Set the flag while INSIDE the lock to block other threads
                if (latest_grid_settings and latest_upper is not None and 
                    latest_lower is not None and not is_paused):
                    allow_place_orders = True
                
                # Clear all orders if it has at least two orders on queue
                if order_snapshot is not None and order_snapshot.get('total_orders') > 1:
                    cancel_all_open_orders(entry_symbol)

                # TRADING LOGIC
                if allow_place_orders:
                    try:
                        # Stamp reservation ticket and let others know is busy now
                        with state.state_lock:
                            if has_running_placing_bot:
                                continue

                            # Claim the ticket
                            has_running_placing_bot = True
                            # ATOMIC PRE-EMPTIVE STRIKE:
                            # We mark it as NOT clean immediately so Thread #2
                            # sees it as dirty before Thread #1 even calls Binance.
                            state.placing_order_state["is_clean"] = False

                        # Snapshot from outside the lock
                        upper = latest_grid_settings['upper']
                        lower = latest_grid_settings['lower']
                        max_pos = latest_grid_settings['max_position_size']
                        order_size = latest_grid_settings['order_size']

                        # Get Current Status from Binance (Network I/O)
                        open_orders = get_open_orders(entry_symbol)   # return list of objects [CurrentAllOpenOrdersResponse]
                        ticker = get_ticker(entry_symbol)
                        positions = get_position(entry_symbol)
                        best_bid = float(ticker.get('best_bid', 0))
                        best_ask = float(ticker.get('best_ask', 0))
                        position_amt = float(positions.get('positionAmt', '0'))
                        abs_position_amt = abs(position_amt)
                        side_position = None    # position_amt = 0 (No position state)
                        
                        if position_amt > 0:
                             side_position = 'BUY'
                        elif position_amt == 0:
                            side_position = None
                        else:
                            side_position = 'SELL'
                        
                        open_price_order = round(float(getattr(open_orders[0], 'price', 0)), 2) if open_orders else 0.0
                        pending_order_size = sum(float(getattr(o, 'orig_qty', 0)) for o in open_orders)

                        # When user open reverse order
                        if side_position != order_snapshot['side'] and side_position is not None:
                            # logger.debug("[User manual order] user open reverse side order!!")
                            pending_order_size = (pending_order_size * -1)

                        # Check if we can open new orders based on max position size compared to current position + pending order size + new order size
                        
                        # Todo: dynamic exposure by latest status: 
                        # position amt -1 -> open buy 0.3 -> -0.7 -> fill open 0.7
                        # position amt 1 -> open sell 0.3 -> 0.7 -> fill open -0.7
                        # position amt 1 -> open buy 0.3 -> 1.3 -> fill open 0.7
                        # total_exposure = position_amt - pending_order_size if order_snapshot['side'] == 'BUY' else position_amt + pending_order_size
                        total_exposure = abs_position_amt + pending_order_size 
                        open_orders_status = ['NEW', 'PARTIALLY_FILLED']
                        remaining_capacity = max_pos - total_exposure
                        is_reach_limit = remaining_capacity <= 0
                        can_open_orders = not is_reach_limit
                        allow_chase_by_status = remaining_capacity >= 0 and order_snapshot['status'] in open_orders_status

                        # State handling position fraction 
                        unfilled_position = ((Decimal(str(abs_position_amt)) * MINIMUM_TRADE_AMOUNT)*CONTRACT_SIZE) % CONTRACT_SIZE
                        same_direction_flag = (order_snapshot['side'] == 'BUY' and position_amt > 0) or (order_snapshot['side'] == 'SELL' and position_amt < 0)
                        dynamic_fraction_by_latest_status = (CONTRACT_SIZE-unfilled_position)  if same_direction_flag else unfilled_position
                        fraction_size = (dynamic_fraction_by_latest_status / CONTRACT_SIZE) * MINIMUM_TRADE_AMOUNT if order_size > 0 else 0
                        has_fractional_position = unfilled_position != 0

                        # Audit log for debugging
                        # logger.debug(f"[Audit placing thread] max_pos: {max_pos}")
                        # logger.debug(f"[Audit placing thread] order_size: {order_size}, allow_place_orders: {allow_place_orders}, total_exposure: {total_exposure}")
                        # logger.debug(f"[Audit placing thread] open_qty_order: {pending_order_size}")
                        # logger.debug(f"[Audit placing thread] is_reach_limit: {is_reach_limit}")
                        # logger.debug(f"[Audit placing thread] remaining_capacity: {remaining_capacity}")
                        # logger.debug(f"[Audit placing thread] Position amount: {position_amt}, Absolute position amount: {abs_position_amt}, has_fractional_position: {has_fractional_position}")
                        # logger.debug(f"[Audit placing thread] can_open_orders: {can_open_orders}, allow_chase_by_status:{allow_chase_by_status}, open_price_order: {open_price_order}, pending_order_size: {pending_order_size}")
                        # logger.debug(f"[Audit placing thread] Fractional position detected. Attempting to clear fraction with size: {fraction_size}")
                        # logger.debug(f"[Audit placing thread] upper: {upper}, lower: {lower}, latest_upper: {latest_upper}, latest_lower: {latest_lower}")
                        # logger.debug(f"[Audit placing thread] order_snapshot: {order_snapshot}, side_position: {side_position}")

                        if has_fractional_position:
                            # Clear left pending order when we reach max_position_size limit
                            if remaining_capacity < 0:
                                cancel_all_open_orders(entry_symbol)

                            side = order_snapshot['side']   # use latest order side for chasing order
                            optimal_price = best_bid - boundary_price if side == 'BUY' else best_ask + boundary_price

                            if allow_chase_by_status:
                                # logger.debug(f"[Fill remain process] Chasing fractional position. Side: {side}, Size: {fraction_size}")
                                chase_order(entry_symbol, fraction_size, side)

                                optimistic_dirty_time = time.time()
                            elif can_open_orders:
                                # logger.debug(f"[Fill remain process] New fractional order. Side: {side}, Size: {fraction_size} >>> SENDING SELL ORDER")
                                response = new_order(entry_symbol, fraction_size, optimal_price, side)

                                # OPTIMISTIC timestamp UPDATE:
                                optimistic_dirty_time = time.time()
                                if response and response.order_id:
                                    last_acted_order_id = response.order_id
                        else:
                            side = order_snapshot['side']

                            # Sell zone
                            if latest_upper >= upper:
                                # logger.debug('[Placing Bot Thread | running algorithm]: Entry sell zone')
                                if allow_chase_by_status:
                                    # Clear left pending order when we reach max_position_size limit
                                    if remaining_capacity < 0:
                                        cancel_all_open_orders(entry_symbol)
                                    elif open_price_order != round(best_ask, 2) and pending_order_size > 0:
                                        chase_order(entry_symbol, pending_order_size, side)
                                elif can_open_orders:
                                    # logger.info("[Placing Bot Thread | running algorithm] >>> SENDING SELL ORDER")
                                    response = new_order(entry_symbol, float(order_size), best_ask + boundary_price, 'SELL')

                                    # OPTIMISTIC timestamp UPDATE:
                                    optimistic_dirty_time = time.time()
                                    if response and response.order_id:
                                        last_acted_order_id = response.order_id

                            # Buy zone
                            elif latest_lower <= lower:
                                # logger.debug('[Placing Bot Thread | running algorithm]: Entry buy zone')
                                if allow_chase_by_status:
                                    # Clear left pending order when we reach max_position_size limit
                                    if remaining_capacity < 0:
                                        cancel_all_open_orders(entry_symbol)
                                    elif open_price_order != round(best_bid, 2) and pending_order_size > 0:
                                        chase_order(entry_symbol, pending_order_size, side)
                                elif can_open_orders:
                                    # logger.info("[Placing Bot Thread | running algorithm] >>> SENDING BUY ORDER")
                                    response = new_order(entry_symbol, float(order_size), best_bid - boundary_price, 'BUY')

                                    # OPTIMISTIC timestamp UPDATE: 
                                    optimistic_dirty_time = time.time()
                                    if response and response.order_id:
                                        last_acted_order_id = response.order_id

                            # Neutral zone
                            else:
                                logger.debug("[Placing Bot Thread | running algorithm] In neutral zone, no new orders will be placed. Monitoring for TP conditions if any open positions exist.")
                                # TP conditions
                                # This code got issued, snowball send order with prebious size e.g [1] 0.03 -> [2] 0.06 -> [3] -> 0.12 , ...
                                # if position_amt != 0:
                                #     close_side = 'SELL' if position_amt > 0 else 'BUY'
                                #     side = 'BUY' if position_amt > 0 else 'SELL'

                                #     if side == 'BUY' and latest_price_diff >= latest_grid_settings['close_long'] and abs_position_amt > 0:
                                #         logger.debug(f"abs_position_amt {abs_position_amt}")
                                #         logger.debug(f"price {best_bid - boundary_price}")
                                #         logger.debug(f"close_side {close_side}")

                                #         # new_order(symbol, abs_position_amt, best_bid - boundary_price, close_side)
                                #     elif side == 'SELL' and latest_price_diff <= latest_grid_settings['close_short'] and abs_position_amt > 0:
                                #         logger.debug(f"abs_position_amt {abs_position_amt}")
                                #         logger.debug(f"price {best_bid - boundary_price}")
                                #         logger.debug(f"close_side {close_side}")
                                #         new_order(symbol, abs_position_amt, best_ask + boundary_price, close_side)
                    except Exception as e:
                        logger.error(f"[Placing Bot Thread] Error in processing grid flow logic: {e}", exc_info=True)
                        # cancel_all_open_orders(symbol)  # Clear all pending orders when server down
                        with state.state_lock:
                            state.placing_order_state["is_clean"] = True
                        time.sleep(1)
                # Done every task and return the reservation ticket
                has_running_placing_bot = False
                time.sleep(0.1)
        except Exception as e:
            logger.error(f"[Placing Bot Thread] Critical PubSub failure: {e}. Reconnecting in 1s...", exc_info=True)
            time.sleep(1)

# function running new thread
def start_grid_bot_sync():

    try:
        PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
        entry_symbol = config.PAIRS[PAIR_INDEX]['entry']['symbol']
        hedge_symbol = config.PAIRS[PAIR_INDEX]['hedge']['symbol']
        logger.info(f"Starting grid trading process for {entry_symbol} ...")

        redis_conn = get_redis_connection()
        pubsub = redis_conn.pubsub()

        price_diff = f"place order of {entry_symbol}"
        grid_range = f"setting_grid_channel:{entry_symbol}:{hedge_symbol}"
        pubsub.subscribe(price_diff, grid_range)

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

