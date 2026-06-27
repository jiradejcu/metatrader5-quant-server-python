import json
import logging
import os
import threading
import time
import websocket
from datetime import datetime

from app.utils.redis_client import get_redis_connection
from app.connectors.binance.api.order import client as binance_client
from app.utils.constants import LOCAL_TZ

logger = logging.getLogger(__name__)
TERMINAL_STATUSES = {'FILLED', 'CANCELED', 'EXPIRED', 'REJECTED', 'EXPIRED_IN_MATCH'}


def watch_user_data_stream(symbol, on_order_update=None):
    """Subscribe to Binance user data stream for real-time order and position updates.

    on_order_update(update) is called on every ORDER_TRADE_UPDATE with:
        order_id, status, fill_pct, side, price, orig_qty, is_clean, status_changed
    """
    WS_BASE = os.getenv("WS_STREAM_URL", "wss://fstream.binance.com")

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

            order_status: dict[str, str] = {}
            _redis = get_redis_connection()

            def on_message(ws, message):
                try:
                    data = json.loads(message)
                    event_type = data.get('e')

                    if event_type == 'ACCOUNT_UPDATE':
                        for p in data.get('a', {}).get('P', []):
                            if p.get('s') == symbol:
                                payload = json.dumps({
                                    'positionAmt': p.get('pa', '0'),
                                    'entryPrice':  p.get('ep', '0'),
                                    'markPrice':   None,
                                    'unRealizedProfit': p.get('up', '0'),
                                    'updateTime':  datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                                })
                                redis_key = f"position:binance:{symbol}"
                                _redis.set(redis_key, payload)
                                _redis.publish(redis_key, payload)
                                _redis.expire(redis_key, 10)
                                logger.debug(
                                    f"[UserDataStream] ACCOUNT_UPDATE: {symbol} positionAmt={p.get('pa')}"
                                )
                                break
                        return

                    if event_type != 'ORDER_TRADE_UPDATE':
                        return
                    o = data.get('o', {})
                    if o.get('s') != symbol:
                        return
                    order_id = o.get('i')
                    new_status = o.get('X')
                    exec_type = o.get('x')          # execution type of THIS event
                    orig_qty = float(o.get('q', 0))
                    executed_qty = float(o.get('z', 0))   # cumulative filled qty
                    last_fill_qty = float(o.get('l', 0))  # qty filled in THIS execution
                    fill_pct = (executed_qty / orig_qty * 100) if orig_qty > 0 else 0
                    last_fill_price = o.get('L')
                    avg_price = o.get('ap')

                    prev_status = order_status.get(order_id)
                    status_changed = new_status != prev_status and new_status is not None
                    if status_changed:
                        logger.debug(
                            f"[UserDataStream] Order {order_id} status {prev_status} → {new_status}"
                        )

                    if on_order_update:
                        on_order_update({
                            "order_id": order_id,
                            "status": new_status,
                            "fill_pct": fill_pct,
                            "side": o.get('S'),
                            "is_clean": new_status in TERMINAL_STATUSES,
                            "price": o.get('p'),
                            "orig_qty": orig_qty,
                            "status_changed": status_changed,
                        })

                    # Log every trade execution, not just orders that reach the
                    # FILLED status. A chased order is often partially filled and
                    # then amended/canceled; that volume still moves the position
                    # but never reaches FILLED, so keying off status under-counts
                    # fills. ``x == 'TRADE'`` fires once per execution with the
                    # incremental ``l`` qty, so logged fills reconcile with the
                    # exchange position.
                    if exec_type == 'TRADE' and last_fill_qty > 0:
                        logger.info(
                            f"[UserDataStream] Order {new_status}: side={o.get('S')} "
                            f"fill_price={last_fill_price} avg_price={avg_price} "
                            f"qty={last_fill_qty}/{orig_qty} order_id={order_id}"
                        )
                    order_status[order_id] = new_status
                    if new_status in TERMINAL_STATUSES:
                        order_status.pop(order_id, None)
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
                f"{WS_BASE}/private/ws/{listen_key}",
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
