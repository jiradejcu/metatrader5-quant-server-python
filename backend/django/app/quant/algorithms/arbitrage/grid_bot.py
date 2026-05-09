import logging
import time
import threading
import os
from . import config
import json
import websocket
from app.utils.redis_client import get_redis_connection
from app.connectors.binance.api.order import get_open_orders, cancel_all_open_orders, chase_order, client as binance_client
from app.connectors.binance.api.position import get_position
from . import state

logger = logging.getLogger(__name__)

latest_grid_settings = None
latest_ask_diff = None
latest_bid_diff = None
def _parse_grid_settings(grid_dict):
    return {
        "upper": float(grid_dict.get('upper_limit', 0.0)),
        "lower": float(grid_dict.get('lower_limit', 0.0)),
        "max_position_size": float(grid_dict.get('max_position_size', 0.0)),
        "order_size": float(grid_dict.get('order_size', 0.0)),
    }


def _determine_zone(ask_diff, bid_diff, upper_limit, lower_limit):
    if ask_diff >= upper_limit:
        return 'SELL'
    if bid_diff <= lower_limit:
        return 'BUY'
    return 'NEUTRAL'


def _compute_target(zone, position_amt, order_size, remaining_capacity):
    """Return desired position amount, or None to do nothing.

    When target == position_amt, reconcile will cancel open orders.
    """
    if zone == 'NEUTRAL' or remaining_capacity <= 0:
        return position_amt  # hold current position — no open order needed

    if zone == 'BUY':
        return position_amt + order_size
    if zone == 'SELL':
        return position_amt - order_size

    return None


def _reconcile(entry_symbol, target, position_amt, open_orders):
    """Take the minimal action to reach the target position."""
    if target is None:
        logger.debug("[Reconcile] do nothing")
        return

    diff = round(target - position_amt, 10)

    if diff == 0:
        if open_orders:
            logger.info(f"[Reconcile] At target position — cancelling {len(open_orders)} open order(s)")
            cancel_all_open_orders(entry_symbol)
        else:
            logger.debug("[Reconcile] At target position — no open orders")
        return

    side = 'BUY' if diff > 0 else 'SELL'
    size = abs(diff)

    if not open_orders:
        logger.info(f"[Reconcile] No open order → chasing {side}, size={size}")
        chase_order(entry_symbol, float(size), side)
        return

    first = open_orders[0]
    current_side = getattr(first, 'side', None)
    current_size = float(getattr(first, 'orig_qty', 0))

    if current_side != side:
        logger.info(
            f"[Reconcile] Wrong side ({current_side} vs target {side}) — cancelling, will re-place next tick"
        )
        cancel_all_open_orders(entry_symbol)
        return

    logger.debug(f"[Reconcile] Chasing {side}, size={current_size}")
    chase_order(entry_symbol, current_size, side)


def _process_tick(entry_symbol, upper_limit, lower_limit, max_pos, order_size,
                  ask_diff, bid_diff):
    """Execute one trading decision from a pubsub tick."""
    with state.state_lock:
        force = state.force_position_fetch
        if force:
            state.force_position_fetch = False

    open_orders = get_open_orders(entry_symbol)
    positions = get_position(entry_symbol, force=force)

    position_amt = float((positions or {}).get('positionAmt', '0'))

    buy_pending = sum(float(getattr(o, 'orig_qty', 0)) for o in open_orders if getattr(o, 'side', '') == 'BUY')
    sell_pending = sum(float(getattr(o, 'orig_qty', 0)) for o in open_orders if getattr(o, 'side', '') == 'SELL')
    net_pending = buy_pending - sell_pending
    remaining_capacity = max_pos - abs(position_amt + net_pending)

    logger.debug(
        f"position={position_amt} open_orders={len(open_orders or [])} "
        f"net_pending={net_pending} remaining_capacity={remaining_capacity:.4f} "
        f"ask_diff={ask_diff:.2f} bid_diff={bid_diff:.2f}"
    )

    if len(open_orders) > 1:
        logger.info(f"Multiple open orders ({len(open_orders)}) — cancelling all before reconcile")
        cancel_all_open_orders(entry_symbol)
        return

    zone = _determine_zone(ask_diff, bid_diff, upper_limit, lower_limit)
    logger.debug(
        f"Zone={zone}: ask_diff={ask_diff:.2f} (limit={upper_limit:.2f}), "
        f"bid_diff={bid_diff:.2f} (limit={lower_limit:.2f})"
    )

    target = _compute_target(zone, position_amt, order_size, remaining_capacity)
    logger.debug(f"Target={target}")

    _reconcile(entry_symbol, target, position_amt, open_orders)


def watch_user_data_stream(entry_symbol):
    """Subscribe to Binance user data stream for real-time order status updates."""
    WS_BASE = os.getenv("WS_STREAM_URL", "wss://fstream.binance.com")
    TERMINAL_STATUSES = {'FILLED', 'CANCELED', 'EXPIRED', 'REJECTED', 'EXPIRED_IN_MATCH'}

    def _keepalive_loop(stop_event):
        while not stop_event.wait(timeout=1800):
            try:
                binance_client.rest_api.keepalive_user_data_stream()
                logger.debug("[UserDataStream] listenKey keepalive sent")
            except Exception as e:
                logger.error(f"[UserDataStream] keepalive failed: {e}")

    while True:
        stop_keepalive = threading.Event()
        try:
            listen_key = binance_client.rest_api.start_user_data_stream().data().listen_key
            logger.info(f"[UserDataStream] Got listenKey, connecting to {WS_BASE}")

            threading.Thread(target=_keepalive_loop, args=(stop_keepalive,), daemon=True).start()

            prev_status = None

            def on_message(ws, message):
                nonlocal prev_status
                try:
                    data = json.loads(message)
                    if data.get('e') != 'ORDER_TRADE_UPDATE':
                        return
                    o = data.get('o', {})
                    if o.get('s') != entry_symbol:
                        return
                    new_status = o.get('X')
                    orig_qty = float(o.get('q', 0))
                    executed_qty = float(o.get('z', 0))
                    fill_pct = (executed_qty / orig_qty * 100) if orig_qty > 0 else 0
                    with state.state_lock:
                        state.placing_order_state.update({
                            "order_id": o.get('i'),
                            "status": new_status,
                            "fill_pct": fill_pct,
                            "side": o.get('S'),
                            "is_clean": new_status in TERMINAL_STATUSES,
                            "price": o.get('p'),
                            "orig_qty": orig_qty,
                        })
                        if new_status != prev_status and new_status is not None:
                            logger.debug(f"[UserDataStream] Order status {prev_status} → {new_status} — flagging force position fetch")
                            state.force_position_fetch = True
                    prev_status = new_status
                except Exception as e:
                    logger.error(f"[UserDataStream] Error processing message: {e}", exc_info=True)

            def on_error(ws, error):
                logger.error(f"[UserDataStream] WebSocket error: {error}")

            def on_close(ws, close_status_code, close_msg):
                logger.warning(f"[UserDataStream] Connection closed: {close_status_code} {close_msg}")
                stop_keepalive.set()

            def on_open(ws):
                logger.info("[UserDataStream] WebSocket connected")

            ws = websocket.WebSocketApp(
                f"{WS_BASE}/ws/{listen_key}",
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            ws.run_forever(ping_interval=60, ping_timeout=10)

        except Exception as e:
            logger.error(f"[UserDataStream] Fatal error: {e}. Reconnecting in 5s...", exc_info=True)
        finally:
            stop_keepalive.set()

        time.sleep(5)


def get_active_status():
    return get_redis_connection().get("grid_bot_active_flag")


PRICE_DIFF_MAX_AGE_MS = int(os.getenv('PRICE_DIFF_MAX_AGE_MS', '300'))


def handle_grid_flow(pubsub, price_diff_key, grid_range_key):
    global latest_grid_settings, latest_ask_diff, latest_bid_diff

    latest_grid_settings = None
    latest_ask_diff = None
    latest_bid_diff = None
    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
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

    # --- Tick worker: runs _process_tick on its own timer, never blocks the pubsub loop ---
    def _tick_worker():
        while True:
            try:
                active = get_active_status()
                allow_place_orders = (
                    latest_grid_settings is not None
                    and latest_ask_diff is not None
                    and latest_bid_diff is not None
                    and active
                )

                if not allow_place_orders:
                    logger.debug(
                        f"[Grid] Orders blocked: "
                        f"has_settings={latest_grid_settings is not None} "
                        f"has_price_diff={latest_ask_diff is not None and latest_bid_diff is not None} "
                        f"active={bool(active)}"
                    )
                else:
                    upper = latest_grid_settings['upper']
                    lower = latest_grid_settings['lower']
                    max_pos = latest_grid_settings['max_position_size']
                    order_size = latest_grid_settings['order_size']

                    _process_tick(
                        entry_symbol,
                        upper, lower, max_pos, order_size,
                        latest_ask_diff, latest_bid_diff,
                    )

            except Exception as e:
                logger.error(f"[Placing Bot Thread] Error in processing grid flow logic: {e}", exc_info=True)

            time.sleep(0.1)

    threading.Thread(target=_tick_worker, daemon=True).start()

    # --- PubSub loop: fast consumer — only updates globals, no Binance API calls ---
    while True:
        try:
            for message in pubsub.listen():
                if message['type'] != 'message':
                    continue

                channel = message['channel'].decode('utf-8')
                data_payload = message['data']

                if channel == price_diff_key:
                    price_dict = json.loads(data_payload) if data_payload else {}
                    msg_ts = price_dict.get('ts')
                    if msg_ts is not None:
                        age_ms = (time.time() - msg_ts) * 1000
                        if age_ms > PRICE_DIFF_MAX_AGE_MS:
                            logger.warning(
                                f"[PubSub] Stale price_diff dropped: age={age_ms:.0f}ms "
                                f"(max={PRICE_DIFF_MAX_AGE_MS}ms) "
                                f"ask_diff={price_dict.get('ask_diff')} bid_diff={price_dict.get('bid_diff')}"
                            )
                            continue
                    latest_ask_diff = round(float(price_dict.get('ask_diff', "0")), 2)
                    latest_bid_diff = round(float(price_dict.get('bid_diff', "0")), 2)
                    logger.debug(f"[PubSub] Price diff updated: upper={latest_ask_diff:.2f}, lower={latest_bid_diff:.2f}")
                elif channel == grid_range_key:
                    latest_grid_settings = _parse_grid_settings(json.loads(data_payload) if data_payload else {})
                    logger.info(f"[PubSub] Grid settings updated: {latest_grid_settings}")

        except Exception as e:
            logger.error(f"[Placing Bot Thread] Critical PubSub failure: {e}. Reconnecting in 1s...", exc_info=True)
            time.sleep(1)


def start_grid_bot_sync():
    if os.environ.get('RUN_MAIN') != 'true':
        return

    try:
        PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
        entry_symbol = config.PAIRS[PAIR_INDEX]['entry']['symbol']
        hedge_symbol = config.PAIRS[PAIR_INDEX]['hedge']['symbol']
        logger.info(f"Starting grid trading process for {entry_symbol} ...")

        redis_conn = get_redis_connection()
        pubsub = redis_conn.pubsub()

        price_diff = f"price_diff:{entry_symbol}:{hedge_symbol}"
        grid_range = f"setting_grid_channel:{entry_symbol}:{hedge_symbol}"
        pubsub.subscribe(price_diff, grid_range)
        logger.info(f"Grid bot subscribed to channels: [{price_diff}], [{grid_range}].")

        threading.Thread(
            target=handle_grid_flow,
            args=(pubsub, price_diff, grid_range), daemon=True
        ).start()
        threading.Thread(
            target=watch_user_data_stream,
            args=(entry_symbol,), daemon=True
        ).start()
        logger.info("Grid Bot thread started and running in background.")
    except Exception as e:
        logger.error(f"Error while syncing grid montinor: {e}", exc_info=True)
