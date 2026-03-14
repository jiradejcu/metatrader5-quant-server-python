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
boundary_price = 10.0
has_running_placing_bot = False # working as reservation ticket (Queue concept - allow one queue works and others will reject if first queue does not finish work)

def poller_snapshot_order_status(symbol):
    logger.info(f"[Poller Order Status Thread] Starting Background Poller for {symbol}")
    while True:
        start_time = time.time() # Capture start time
        try:
            snapshot = get_latest_order_snapshot(symbol)
            
            with state.state_lock:
                state.placing_order_state["order_id"] = snapshot.get('order_id', None) if snapshot else None
                state.placing_order_state["status"] = snapshot.get('status', None) if snapshot else None
                state.placing_order_state["fill_pct"] = snapshot.get('fill_pct', 0) if snapshot else 0
                state.placing_order_state["side"] = snapshot.get('side', None) if snapshot else None
                state.placing_order_state["is_clean"] = snapshot.get('is_clean', True) if snapshot else True
        except Exception as e:
            logger.error(f"Poller Thread Error: {e}")
            time.sleep(1) # Wait longer on error

        # 0.5 seconds = 120 calls per minute. 
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
    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    CONTRACT_SIZE = int(os.getenv('CONTRACT_SIZE'))
    MINIMUM_TRADE_AMOUNT = int(os.getenv('MINIMUM_TRADE_AMOUNT'))
    symbol = config.PAIRS[PAIR_INDEX]['binance']

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

                with state.state_lock:
                    order_snapshot = state.placing_order_state.copy()
                
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

                # TRADING LOGIC
                if allow_place_orders and not has_running_placing_bot:
                    try:
                        # Stamp reservation ticket and let others know is busy now
                        has_running_placing_bot = True

                        # Snapshot from outside the lock
                        upper = latest_grid_settings['upper']
                        lower = latest_grid_settings['lower']
                        max_pos = latest_grid_settings['max_position_size']
                        order_size = latest_grid_settings['order_size']

                        # Get Current Status from Binance (Network I/O)
                        open_orders = get_open_orders(symbol)   # return list of objects [CurrentAllOpenOrdersResponse]
                        ticker = get_ticker(symbol)
                        best_bid = float(ticker.get('best_bid', 0))
                        best_ask = float(ticker.get('best_ask', 0))
                        positions = get_position(symbol)
                        position_amt = float(positions.get('positionAmt', '0'))
                        abs_position_amt = abs(position_amt)
                        open_price_order = round(float(getattr(open_orders[0], 'price', 0)), 2) if open_orders else 0.0
                        pending_order_size = sum(float(getattr(o, 'orig_qty', 0)) for o in open_orders)

                        # Check if we can open new orders based on max position size compared to current position + pending order size + new order size
                        total_exposure = abs_position_amt + pending_order_size
                        open_orders_status = ['NEW', 'PARTIALLY_FILLED']
                        remaining_capacity = max_pos - total_exposure
                        is_reach_limit = remaining_capacity <= 0
                        can_open_orders = not is_reach_limit and order_snapshot['is_clean']
                        allow_chase_by_status = remaining_capacity >= 0 and order_snapshot['status'] in open_orders_status

                        # State handling position fraction 
                        unfilled_position = ((Decimal(str(abs_position_amt)) * MINIMUM_TRADE_AMOUNT)*CONTRACT_SIZE) % CONTRACT_SIZE
                        fraction_size = ((CONTRACT_SIZE-unfilled_position) / CONTRACT_SIZE) * MINIMUM_TRADE_AMOUNT
                        has_fractional_position = unfilled_position != 0

                        # Circuit remove pending open order if current position size hit limit max position
                        if is_reach_limit and open_orders:
                            logger.debug("Circuit removing open order to prevent fill over max position size.")
                            cancel_all_open_orders(symbol)

                        # Audit log for debugging
                        logger.debug(f"[Audit placing thread] max_pos: {max_pos}")
                        logger.debug(f"[Audit placing thread] order_size: {order_size}, allow_place_orders: {allow_place_orders}, total_exposure: {total_exposure}")
                        logger.debug(f"[Audit placing thread] open_qty_order: {pending_order_size}")
                        logger.debug(f"[Audit placing thread] is_reach_limit: {is_reach_limit}")
                        logger.debug(f"[Audit placing thread] remaining_capacity: {remaining_capacity}")
                        logger.debug(f"[Audit placing thread] Position amount: {position_amt}, Absolute position amount: {abs_position_amt}, has_fractional_position: {has_fractional_position}")
                        logger.debug(f"[Audit placing thread] can_open_orders: {can_open_orders}, allow_chase_by_status:{allow_chase_by_status}, open_price_order: {open_price_order}, pending_order_size: {pending_order_size}")
                        logger.debug(f"[Audit placing thread] Fractional position detected. Attempting to clear fraction with size: {fraction_size}")
                        logger.debug(f"[Audit placing thread] upper: {upper}, lower: {lower}, latest_upper: {latest_upper}, latest_lower: {latest_lower}")
                        logger.debug(f"[Audit placing thread] order_snapshot: {order_snapshot}")

                        if has_fractional_position:   
                            # If the pending order size is not equal to the required fraction size, we need to cancel existing orders and place a new chase order for the fraction size.                         
                            if pending_order_size != fraction_size:
                                cancel_all_open_orders(symbol)
                            
                            side = order_snapshot['side']   # use latest order side for chasing order

                            if can_open_orders:
                                logger.debug(f"[Fill remain process] New fractional order. Side: {side}, Size: {fraction_size}")
                                new_order(symbol, fraction_size, best_ask + boundary_price, side)
                            else:
                                if allow_chase_by_status:
                                    logger.debug(f"[Fill remain process] Chasing fractional position. Side: {side}, Size: {fraction_size}")
                                    chase_order(symbol, fraction_size, side)
                        else:
                            side = order_snapshot['side']
                            
                            # Sell zone
                            if latest_upper >= upper:
                                logger.debug(f"[Placing Bot Thread | running algorithm] Sell zone detected. Latest upper: {latest_upper} is greater than or equal to upper threshold: {upper}")
                                if open_orders:
                                    # Clear left pending order when we reach max_position_size limit
                                    if remaining_capacity < 0:
                                        cancel_all_open_orders(symbol)
                                    elif open_price_order != round(best_ask, 2) and pending_order_size > 0 and allow_chase_by_status:
                                        chase_order(symbol, pending_order_size, side)                                  
                                elif can_open_orders:
                                    new_order(symbol, float(order_size), best_ask + boundary_price, 'SELL')

                            # Buy zone
                            elif latest_lower <= lower:
                                logger.debug(f"[Placing Bot Thread | running algorithm] Buy zone detected. Latest lower: {latest_lower} is less than or equal to lower threshold: {lower}")
                                if open_orders:
                                    # Clear left pending order when we reach max_position_size limit
                                    if remaining_capacity < 0:
                                        cancel_all_open_orders(symbol)
                                    elif open_price_order != round(best_bid, 2) and pending_order_size > 0 and allow_chase_by_status:
                                        chase_order(symbol, pending_order_size, side)
                                elif can_open_orders:
                                    new_order(symbol, float(order_size), best_bid - boundary_price, 'BUY')

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
                        # Done every task and return the reservation ticket
                        has_running_placing_bot = False
                    except Exception as e:
                        logger.error(f"[Placing Bot Thread] Error in processing grid flow logic: {e}", exc_info=True)
                        cancel_all_open_orders(symbol)  # Clear all pending orders when server down
                        has_running_placing_bot = False # Reset reservation ticket process
                        time.sleep(1)
        except Exception as e:
            logger.error(f"[Placing Bot Thread] Critical PubSub failure: {e}. Reconnecting in 1s...", exc_info=True)
            time.sleep(1)

# function running new thread
def start_grid_bot_sync():

    try:
        PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
        binance_symbol = config.PAIRS[PAIR_INDEX]['binance']
        mt5_symbol = config.PAIRS[PAIR_INDEX]['mt5']
        logger.info(f"Starting grid trading process for {binance_symbol} ...")

        redis_conn = get_redis_connection()
        pubsub = redis_conn.pubsub()

        price_diff = f"place order of {binance_symbol}"
        grid_range = f"setting_grid_channel:{binance_symbol}:{mt5_symbol}"
        pubsub.subscribe(price_diff, grid_range)

        threading.Thread(
            target=handle_grid_flow,
            args=(pubsub, price_diff, grid_range), daemon=True
        ).start()
        threading.Thread(
            target=poller_snapshot_order_status,
            args=(binance_symbol,), daemon=True
        ).start()
        logger.info("Grid Bot thread started and running in background.")
    except Exception as e:
        logger.error(f"Error while syncing grid montinor: {e}", exc_info=True)

