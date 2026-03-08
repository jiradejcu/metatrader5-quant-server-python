import logging
import time
import threading
import os
from . import config
from decimal import Decimal
import json
import os
from app.utils.redis_client import get_redis_connection
from app.connectors.binance.api.order import get_open_orders, cancel_all_open_orders, chase_order, new_order
from app.connectors.binance.api.ticker import get_ticker
from app.connectors.binance.api.position import get_position

logger = logging.getLogger(__name__)

# For securing uses global from many threads
data_lock = threading.Lock()
latest_update = None
latest_grid_settings = None
latest_upper = None
latest_lower = None
boundary_price = 10.0
is_processing_place_order = False

def get_pause_status():
    redis_conn = get_redis_connection()
    redis_key= "grid_bot_paused_flag"
    is_paused = redis_conn.get(redis_key)
    return is_paused

def handle_grid_flow(pubsub, price_diff_key, grid_range_key):
    global latest_update, latest_grid_settings, is_processing_place_order, latest_upper, latest_lower
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
            with data_lock: # Prevent race conditions
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

                if is_processing_place_order:
                    logger.debug("Currently processing an order, skipping other messages to avoid race conditions.")
                    continue

                channel = message['channel'].decode('utf-8')
                data_payload = message['data']
                allow_place_orders = False

                with data_lock:
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
                        logger.info(f"Grid settings updated via Pub/Sub: {latest_grid_settings}")
                    
                    is_paused = get_pause_status()

                    # Audit metrics for enabling informed decision in placing orders
                    logger.debug(f"Latest upper diff: {latest_upper}, Latest lower diff: {latest_lower}, Is paused: {is_paused}, Is processing place order: {is_processing_place_order}")
                    # Set the flag while INSIDE the lock to block other threads
                    if (latest_grid_settings and latest_upper is not None and 
                        latest_lower is not None and not is_paused and not is_processing_place_order):
                        is_processing_place_order = True
                        allow_place_orders = True

                # TRADING LOGIC (OUTSIDE OF DATA_LOCK)
                if allow_place_orders:
                    try:
                        # previous order status propagate through the exchange API
                        time.sleep(0.5) 
                        
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
                        remaining_capacity = max_pos - total_exposure
                        open_one_order = True if pending_order_size > 0 else False
                        is_reach_limit = remaining_capacity <= 0
                        available_slots = remaining_capacity / order_size if (order_size > 0 and remaining_capacity > 0) else 0
                        # Floating Point Safety using 0.99
                        can_open_orders = not is_reach_limit and available_slots >= 0.99 and not open_one_order

                        # State handling position fraction 
                        unfilled_position = ((Decimal(str(abs_position_amt)) * MINIMUM_TRADE_AMOUNT)*CONTRACT_SIZE) % CONTRACT_SIZE
                        fraction_size = ((CONTRACT_SIZE-unfilled_position) / CONTRACT_SIZE) * MINIMUM_TRADE_AMOUNT

                        check_limit = max_pos - (abs_position_amt + float(fraction_size))
                        has_fractional_position = unfilled_position != 0

                        # Circuit remove open order if is_reach_limit <=0 but we have open_one_order to free up capacity for new order
                        if is_reach_limit and open_orders:
                            logger.debug("Circuit removing open order to prevent fill over max position size.")
                            cancel_all_open_orders(symbol)

                        # Audit log for debugging
                        # logger.debug(f"max_pos: {max_pos}")
                        # logger.debug(f"order_size: {order_size}, allow_place_orders: {allow_place_orders}, total_exposure: {total_exposure}")
                        # logger.debug(f"open_qty_order: {pending_order_size}")
                        # logger.debug(f"is_processing_place_order: {is_processing_place_order}")
                        # logger.debug(f"is_reach_limit: {is_reach_limit}, available_slots: {available_slots}, open_one_order: {open_one_order}")
                        # logger.debug(f"remaining_capacity: {remaining_capacity}")
                        # logger.debug(f"Position amount: {position_amt}, Absolute position amount: {abs_position_amt}")
                        # logger.debug(f"can_open_orders: {can_open_orders}, open_price_order: {open_price_order}, pending_order_size: {pending_order_size}")
                        # logger.debug(f"Fractional position detected. Attempting to clear fraction with size: {fraction_size}")
                        # logger.debug(f"upper: {upper}, lower: {lower}, latest_upper: {latest_upper}, latest_lower: {latest_lower}")

                        if has_fractional_position:   
                            # If the pending order size is not equal to the required fraction size, we need to cancel existing orders and place a new chase order for the fraction size.                         
                            if pending_order_size != fraction_size:
                                cancel_all_open_orders(symbol)
                            
                            side = 'BUY' if position_amt > 0 else 'SELL'
                            logger.debug(f"Chasing fractional position. Side: {side}, Size: {fraction_size}")

                            if check_limit >= 0:
                                chase_order(symbol, fraction_size, side)
                        else:
                            # Sell zone
                            if latest_upper >= upper:
                                logger.debug(f"Sell zone detected. Latest upper: {latest_upper} is greater than or equal to upper threshold: {upper}")
                                if open_orders:
                                    # Clear left pending order when we reach max_position_size limit
                                    if remaining_capacity < 0:
                                        cancel_all_open_orders(symbol)
                                    elif open_price_order != round(best_ask, 2) and pending_order_size > 0 and check_limit >= 0:
                                        chase_order(symbol, pending_order_size, 'SELL')                                  
                                elif can_open_orders:
                                    new_order(symbol, float(order_size), best_ask + boundary_price, 'SELL')

                            # Buy zone
                            elif latest_lower <= lower:
                                logger.debug(f"Buy zone detected. Latest lower: {latest_lower} is less than or equal to lower threshold: {lower}")
                                if open_orders:
                                    if remaining_capacity < 0:
                                        # Clear left pending order when we reach max_position_size limit
                                        cancel_all_open_orders(symbol)
                                    elif open_price_order != round(best_bid, 2) and pending_order_size > 0 and check_limit >= 0:
                                        chase_order(symbol, pending_order_size, 'BUY')
                                elif can_open_orders:
                                    new_order(symbol, float(order_size), best_bid - boundary_price, 'BUY')

                            # Neutral zone
                            else:
                                logger.debug("In neutral zone, no new orders will be placed. Monitoring for TP conditions if any open positions exist.")
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
                        logger.error(f"Error in processing grid flow logic: {e}", exc_info=True)
                        # Clear all pending orders when server down
                        cancel_all_open_orders(symbol)
                        time.sleep(3)
                    finally:
                        # ALWAYS reset flag inside finally and inside lock
                        # Wait a moment for the order to "settle" in the exchange system
                        time.sleep(1) 
                        with data_lock:
                            is_processing_place_order = False
        except Exception as e:
            logger.error(f"Critical PubSub failure: {e}. Reconnecting in 5s...", exc_info=True)
            time.sleep(5)

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
        logger.info("Grid Bot thread started and running in background.")
    except Exception as e:
        logger.error(f"Error while syncing grid montinor: {e}", exc_info=True)

