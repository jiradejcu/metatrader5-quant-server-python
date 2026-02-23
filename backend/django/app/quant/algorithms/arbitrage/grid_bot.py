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
latest_price_diff = None
boundary_price = 10.0
is_processing_place_order = False

def get_pause_status():
    redis_conn = get_redis_connection()
    redis_key= "grid_bot_paused_flag"
    is_paused = redis_conn.get(redis_key)
    return is_paused

def handle_grid_flow(pubsub, price_diff_key, grid_range_key):
    global latest_update, latest_grid_settings, latest_price_diff, is_processing_place_order
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

            with data_lock:
                is_pause = get_pause_status()
                # logger.debug(f"Grid Bot status: {'Paused' if is_pause else 'Active'}")
                # logger.debug(f"latest_grid_settings: {latest_grid_settings}, latest_price_diff: {latest_price_diff}")
                # logger.debug(f"Check flag: {latest_grid_settings is not None and latest_price_diff is not None and is_pause is None}")
                if channel == price_diff_key:
                    price_dict = json.loads(data_payload) if data_payload else {}
                    latest_price_diff = round(float(price_dict.get('percent_change_premium', "0")), 3)
                    
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

                # --- Trading Logic Execution ---
                if latest_grid_settings is not None and latest_price_diff is not None and is_pause is None:
                    is_processing_place_order = True
                    try:
                        upper = latest_grid_settings['upper']
                        logger.debug(f"Sell zone: {latest_price_diff >= upper}")
                        lower = latest_grid_settings['lower']
                        max_pos = latest_grid_settings['max_position_size']
                        order_size = latest_grid_settings['order_size']

                        # Get Current Status
                        open_orders = get_open_orders(symbol)   # return list of objects [CurrentAllOpenOrdersResponse]
                        logger.debug(f"Open orders fetched: {open_orders}")
                        ticker = get_ticker(symbol)
                        best_bid = float(ticker.get('best_bid', 0))
                        best_ask = float(ticker.get('best_ask', 0))
                        positions = get_position(symbol)
                        position_amt = float(positions.get('positionAmt', '0'))
                        abs_position_amt = abs(position_amt)

                        open_price_order = round(float(getattr(open_orders[0], 'price', 0)), 2) if open_orders else 0.0
                        pending_order_size = sum(float(getattr(o, 'orig_qty', 0)) for o in open_orders)

                        
                        # logger.debug(f"abs_position_amt: {abs_position_amt} ")
                        # logger.debug(f"order_size: {order_size} ")
                        # logger.debug(f"open_qty_order: {pending_order_size} ")
                        # logger.debug(f"max_pos: {max_pos} ")

                        # Check if we can open new orders based on max position size compared to current position + pending order size + new order size
                        # Now waiting to find the way to handle race condition issue.
                        total_exposure = abs_position_amt + pending_order_size
                        remaining_capacity = max_pos - total_exposure
                        open_one_order = True if pending_order_size >= float(order_size) else False

                        is_reach_limit = remaining_capacity <= 0
                        available_slots = remaining_capacity / order_size if order_size > 0 else 0

                        # Floating Point Safety using 0.99
                        can_open_orders = not is_reach_limit and available_slots >= 0.99 and not open_one_order
                        # add more condition to num_open_order should be (max_pos - abs_position_amt) / order_size to prevent open too many orders when max_pos is much bigger than order_size

                        # logger.debug(f"can_open_orders: {can_open_orders}")
                        # logger.debug(f"open_orders: {open_orders}")
                        # logger.debug(f"best_bid: {best_bid}, best_ask: {best_ask}")

                        # State handling position fraction 
                        # by f != 0 then we need to clear this position by chase order with qty =  contract size and side is the same as current position side
                        f = ((Decimal(str(abs_position_amt)) * MINIMUM_TRADE_AMOUNT)*CONTRACT_SIZE) % CONTRACT_SIZE
                        # logger.debug(f"Position amount: {position_amt}, Absolute position amount: {abs_position_amt}, Fractional part (f): {f}")
                        has_fractional_position = f != 0

                        if has_fractional_position:
                            logger.debug("Fractional position detected. Initiating cancellation of all open orders to clear fraction.")
                            # cancel_all_open_orders(symbol)
                            
                            fraction_size = ((CONTRACT_SIZE-f) / CONTRACT_SIZE) * MINIMUM_TRADE_AMOUNT
                            logger.debug(f"Fractional position detected. Attempting to clear fraction with size: {fraction_size}")

                            if pending_order_size == fraction_size:
                                side = 'BUY' if position_amt > 0 else 'SELL'
                                chase_order(symbol, fraction_size, side)
                            else:
                                cancel_all_open_orders(symbol)
                        else:
                            # Sell zone
                            if latest_price_diff >= upper:
                                logger.debug(f"Sell zone detected. Latest price diff: {latest_price_diff} is greater than or equal to upper threshold: {upper}")
                                if open_orders:
                                    if open_price_order != round(best_ask, 2) and pending_order_size > 0:
                                        chase_order(symbol, pending_order_size, 'SELL')                                  
                                elif can_open_orders:
                                    new_order(symbol, float(order_size), best_ask + boundary_price, 'SELL')

                            # Buy zone
                            elif latest_price_diff <= lower:
                                logger.debug(f"Buy zone detected. Latest price diff: {latest_price_diff} is less than or equal to lower threshold: {lower}")
                                if open_orders:
                                    if open_price_order != round(best_bid, 2) and pending_order_size > 0:
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
                                        # new_order(symbol, abs_position_amt, best_ask + boundary_price, close_side)
                        
                        # logger.info(f"Grid logic processed for price diff: {latest_price_diff} with settings: {latest_grid_settings}")
                    finally:
                        # Unlock the flag after processing to allow new messages to be handled
                        is_processing_place_order = False
    except Exception as e:
        logger.error(f"Error handle grid flow process because: {e}", exc_info=True)

# function running new thread
def start_grid_bot_sync():

    try:
        PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
        binance_symbol = config.PAIRS[PAIR_INDEX]['binance']
        mt5_symbol = config.PAIRS[PAIR_INDEX]['mt5']
        logger.info(f"Starting grid trading process for {binance_symbol} ...")

        redis_conn = get_redis_connection()
        pubsub = redis_conn.pubsub()

        price_diff = f"price_comparison:{binance_symbol}:{mt5_symbol}"
        grid_range = f"setting_grid_channel:{binance_symbol}:{mt5_symbol}"
        pubsub.subscribe(price_diff, grid_range)

        threading.Thread(
            target=handle_grid_flow,
            args=(pubsub, price_diff, grid_range), daemon=True
        ).start()
        logger.info("Grid Bot thread started and running in background.")
    except Exception as e:
        logger.error(f"Error while syncing grid montinor: {e}", exc_info=True)

