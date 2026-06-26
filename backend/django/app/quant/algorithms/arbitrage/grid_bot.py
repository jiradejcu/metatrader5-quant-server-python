import logging
import math
import time
import threading
import os
from datetime import datetime, timezone
from . import config
import json
from app.utils.redis_client import get_redis_connection
from app.connectors.binance.api.order import get_open_orders, cancel_all_open_orders, chase_order
from app.connectors.binance.api.position import get_position
from app.connectors.binance.api.user_data_stream import watch_user_data_stream
from .price_diff import PRICE_DIFF_MAX_AGE_MS
from . import state

logger = logging.getLogger(__name__)

latest_grid_settings = None
latest_ask_diff = None
latest_bid_diff = None
latest_price_ts = None
latest_atr = 0.0
_prev_ask_diff_for_atr = None
_prev_bid_diff_for_atr = None

# Asymmetric EMA: a short period reacts fast when volatility rises (TR > ATR),
# a long period lets ATR decay slowly back down once it falls (TR < ATR), so
# the guard trips quickly but stays blocked for a while after a spike.
ATR_PERIOD = int(os.getenv('ATR_PERIOD', '2'))
ATR_PERIOD_DOWN = int(os.getenv('ATR_PERIOD_DOWN', '7'))
_ATR_ALPHA_UP = 2.0 / (ATR_PERIOD + 1)
_ATR_ALPHA_DOWN = 2.0 / (ATR_PERIOD_DOWN + 1)
ATR_HIGH_THRESHOLD = float(os.getenv('ATR_HIGH_THRESHOLD', '0.3'))



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


def _compute_target(zone, position_amt, order_size, max_pos, net_pending=0):
    """Return desired position amount, or None to do nothing.

    When target == position_amt, reconcile will cancel open orders.

    In MOCK_ENTRY_POSITION_AMT mode the result is truncated to the nearest
    1/contract_size lot (from config.PAIRS[PAIR_INDEX]); otherwise it is
    truncated to the nearest integer.
    Example (contract_size=100, order_size=0.012):
        trunc(0.012 × 100) / 100 = 0.01.

    net_pending: buy_pending - sell_pending from open orders.
                 remaining_capacity == 0 with same-direction position: a pending
                 order legitimately fills the last slot — return the committed
                 target so reconcile chases it instead of cancelling.
                 remaining_capacity == 0 with opposite-direction position: order
                 reduces abs(position), so capacity is not truly exhausted.
                 remaining_capacity < 0: over-committed — cancel excess order.
    """
    def _trunc(val):
        if os.getenv('MOCK_ENTRY_POSITION_AMT', 'false').lower() == 'true':
            contract_size = config.PAIRS[int(os.getenv('PAIR_INDEX', '0'))]['contract_size']
            return math.trunc(val * contract_size) / contract_size
        return math.trunc(val)

    # +order_size for BUY, -order_size for SELL, None for NEUTRAL.
    zone_delta = {'BUY': order_size, 'SELL': -order_size}.get(zone)

    if zone_delta is None:
        return _trunc(position_amt)

    remaining_capacity = max_pos - abs(position_amt + net_pending)

    # Order is opposite to current position: it reduces abs(position), so place it
    # regardless of capacity — even when max_pos was lowered below current position.
    # Clamp so the result doesn't overshoot past max_pos on the opposite side.
    # BUY reduces a short: cap at +max_pos. SELL reduces a long: floor at -max_pos.
    if position_amt * zone_delta < 0:
        raw = position_amt + zone_delta
        if raw * position_amt < 0:
            return 0
        if zone_delta > 0:
            return _trunc(min(raw, max_pos))
        else:
            return _trunc(max(raw, -max_pos))

    # Same-direction order below: check capacity.
    if remaining_capacity > 0:
        return _trunc(position_amt + zone_delta)

    # remaining_capacity == 0: a pending order fills the last slot — chase it.
    if remaining_capacity == 0:
        return _trunc(position_amt + net_pending)

    # remaining_capacity < 0: over-committed — hold so reconcile cancels excess order.
    return _trunc(position_amt)


def _reconcile(primary_symbol, target, position_amt, open_orders, sync_pending=False):
    """Take the minimal action to reach the target position."""
    if target is None:
        logger.debug("[Reconcile] do nothing")
        return

    diff = round(target - position_amt, 10)

    if diff == 0:
        if open_orders:
            logger.info(f"[Reconcile] At target position — cancelling {len(open_orders)} open order(s)")
            cancel_all_open_orders(primary_symbol)
        else:
            logger.debug("[Reconcile] At target position — no open orders")
        return

    side = 'BUY' if diff > 0 else 'SELL'
    size = abs(diff)

    if not open_orders:
        if sync_pending:
            logger.info(f"[Reconcile] Sync pending — holding off on new {side} order")
            return
        logger.info(f"[Reconcile] No open order → placing {side}, size={size}")
        chase_order(primary_symbol, float(size), side, order_id=None)
        return

    first = open_orders[0]
    current_side = getattr(first, 'side', None)
    current_size = float(getattr(first, 'orig_qty', 0))
    current_order_id = getattr(first, 'order_id', None)

    if current_side != side:
        logger.info(
            f"[Reconcile] Wrong side ({current_side} vs target {side}) — cancelling, will re-place next tick"
        )
        cancel_all_open_orders(primary_symbol)
        return

    logger.debug(f"[Reconcile] Chasing {side}, order_id={current_order_id}, size={current_size}")
    chase_order(primary_symbol, current_size, side, order_id=current_order_id)


def _process_tick(primary_symbol, upper_limit, lower_limit, max_pos, order_size,
                  ask_diff, bid_diff):
    """Execute one trading decision from a pubsub tick."""
    with state.state_lock:
        force = state.force_fetch
        if force:
            state.force_fetch = False

    open_orders = get_open_orders(primary_symbol, force=force)
    positions = get_position(primary_symbol, force=force)

    position_amt = float((positions or {}).get('positionAmt', '0'))

    buy_pending = sum(float(getattr(o, 'orig_qty', 0)) for o in open_orders if getattr(o, 'side', '') == 'BUY')
    sell_pending = sum(float(getattr(o, 'orig_qty', 0)) for o in open_orders if getattr(o, 'side', '') == 'SELL')
    net_pending = buy_pending - sell_pending

    # Refresh price after slow API calls — use the freshest diff available
    if latest_ask_diff is not None and latest_bid_diff is not None:
        if ask_diff != latest_ask_diff or bid_diff != latest_bid_diff:
            logger.debug(
                f"Price refreshed after API calls: "
                f"ask_diff {ask_diff:.2f}→{latest_ask_diff:.2f}, "
                f"bid_diff {bid_diff:.2f}→{latest_bid_diff:.2f}"
            )
        ask_diff = latest_ask_diff
        bid_diff = latest_bid_diff

    if latest_atr > ATR_HIGH_THRESHOLD:
        logger.warning(
            f"[Grid] High volatility — skipping tick: "
            f"ATR={latest_atr:.3f} > threshold={ATR_HIGH_THRESHOLD}"
        )
        return

    logger.debug(
        f"position={position_amt} open_orders={len(open_orders or [])} "
        f"net_pending={net_pending} max_pos={max_pos} ask_diff={ask_diff:.2f} bid_diff={bid_diff:.2f}"
    )

    if len(open_orders) > 1:
        logger.info(f"Multiple open orders ({len(open_orders)}) — cancelling all before reconcile")
        cancel_all_open_orders(primary_symbol)
        return

    zone = _determine_zone(ask_diff, bid_diff, upper_limit, lower_limit)
    logger.debug(
        f"Zone={zone}: ask_diff={ask_diff:.2f} (limit={upper_limit:.2f}), "
        f"bid_diff={bid_diff:.2f} (limit={lower_limit:.2f})"
    )

    target = _compute_target(zone, position_amt, order_size, max_pos, net_pending=net_pending)
    logger.debug(f"Target={target}")

    if latest_price_ts is not None:
        price_age_ms = (time.monotonic() - latest_price_ts) * 1000
        if price_age_ms > PRICE_DIFF_MAX_AGE_MS:
            logger.warning(f"Price diff is stale ({price_age_ms:.0f}ms > {PRICE_DIFF_MAX_AGE_MS}ms) — skipping reconcile")
            return

    sync_pending = get_sync_pending()
    _reconcile(primary_symbol, target, position_amt, open_orders, sync_pending=bool(sync_pending))


_DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

def _is_within_trading_session(primary_symbol, hedge_symbol):
    """Return True if current UTC time falls within a configured trading session window.

    If no session config is stored in Redis, returns True (unrestricted).
    Time ranges use "HH:MM" strings; "24:00" means end of day.
    """
    try:
        redis_conn = get_redis_connection()
        key = f"trading_sessions:{primary_symbol}:{hedge_symbol}"
        raw = redis_conn.get(key)
        if not raw:
            return True

        sessions = json.loads(raw)
        now_utc = datetime.now(timezone.utc)
        day_name = _DAY_NAMES[now_utc.weekday()]
        ranges = sessions.get(day_name, [])

        current_minutes = now_utc.hour * 60 + now_utc.minute

        for r in ranges:
            start_h, start_m = map(int, r['start'].split(':'))
            end_h, end_m = map(int, r['end'].split(':'))
            start_min = start_h * 60 + start_m
            end_min = end_h * 60 + end_m  # 24:00 → 1440, always > any valid time
            if start_min <= current_minutes < end_min:
                return True

        return False
    except Exception as e:
        logger.warning(f"[Session] Failed to check trading session, allowing tick: {e}")
        return True


def get_active_status():
    return get_redis_connection().get("grid_bot_active_flag")


def get_position_sync_ok():
    return get_redis_connection().get("position_sync_ok_flag")


def get_sync_pending():
    return get_redis_connection().get("sync_pending_flag")


def handle_grid_flow(pubsub, price_diff_key, grid_range_key, hedge_symbol):
    global latest_grid_settings, latest_ask_diff, latest_bid_diff, latest_price_ts, latest_atr, _prev_ask_diff_for_atr, _prev_bid_diff_for_atr

    latest_grid_settings = None
    latest_ask_diff = None
    latest_bid_diff = None
    latest_price_ts = None
    latest_atr = 0.0
    _prev_ask_diff_for_atr = None
    _prev_bid_diff_for_atr = None
    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    primary_symbol = config.PAIRS[PAIR_INDEX]['primary']['symbol']

    # --- Initial Fetch for Grid Settings ---
    try:
        redis_conn = get_redis_connection()
        initial_grid_data = redis_conn.get(grid_range_key)
        if initial_grid_data:
            latest_grid_settings = _parse_grid_settings(json.loads(initial_grid_data))
            logger.debug(f"Initial grid settings loaded: {latest_grid_settings}")
    except Exception as e:
        logger.error(f"Failed to fetch initial grid settings: {e}")

    _new_price_event = threading.Event()

    # --- Tick worker: wakes only when a new price diff arrives ---
    def _tick_worker():
        while True:
            _new_price_event.wait()
            _new_price_event.clear()
            try:
                active = get_active_status()
                sync_ok = get_position_sync_ok()
                allow_place_orders = (
                    latest_grid_settings is not None
                    and latest_ask_diff is not None
                    and latest_bid_diff is not None
                    and active
                    and sync_ok
                )

                if not allow_place_orders:
                    logger.debug(
                        f"[Grid] Orders blocked: "
                        f"has_settings={latest_grid_settings is not None} "
                        f"has_price_diff={latest_ask_diff is not None and latest_bid_diff is not None} "
                        f"position_sync_ok={bool(sync_ok)} "
                        f"active={bool(active)}"
                    )
                elif not _is_within_trading_session(primary_symbol, hedge_symbol):
                    logger.debug("[Grid] Outside trading session — skipping tick")
                else:
                    upper = latest_grid_settings['upper']
                    lower = latest_grid_settings['lower']
                    max_pos = latest_grid_settings['max_position_size']
                    order_size = latest_grid_settings['order_size']

                    _process_tick(
                        primary_symbol,
                        upper, lower, max_pos, order_size,
                        latest_ask_diff, latest_bid_diff,
                    )

            except Exception as e:
                logger.error(f"[Placing Bot Thread] Error in processing grid flow logic: {e}", exc_info=True)

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
                    new_ask_diff = round(float(price_dict.get('ask_diff', "0")), 2)
                    new_bid_diff = round(float(price_dict.get('bid_diff', "0")), 2)
                    if _prev_ask_diff_for_atr is not None and _prev_bid_diff_for_atr is not None:
                        tr = max(abs(new_ask_diff - _prev_ask_diff_for_atr), abs(new_bid_diff - _prev_bid_diff_for_atr))
                        alpha = _ATR_ALPHA_UP if tr > latest_atr else _ATR_ALPHA_DOWN
                        latest_atr = alpha * tr + (1 - alpha) * latest_atr
                    _prev_ask_diff_for_atr = new_ask_diff
                    _prev_bid_diff_for_atr = new_bid_diff
                    latest_ask_diff = new_ask_diff
                    latest_bid_diff = new_bid_diff
                    latest_price_ts = time.monotonic()
                    _new_price_event.set()
                    logger.debug(
                        f"[PubSub] Price diff updated: ask_diff={latest_ask_diff:.2f}, "
                        f"bid_diff={latest_bid_diff:.2f}, atr={latest_atr:.3f}"
                    )
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
        primary_symbol = config.PAIRS[PAIR_INDEX]['primary']['symbol']
        hedge_symbol = config.PAIRS[PAIR_INDEX]['hedge']['symbol']
        logger.info(f"Starting grid trading process for {primary_symbol} ...")

        redis_conn = get_redis_connection()
        pubsub = redis_conn.pubsub()

        price_diff = f"price_diff:{primary_symbol}:{hedge_symbol}"
        grid_range = f"setting_grid_channel:{primary_symbol}:{hedge_symbol}"
        pubsub.subscribe(price_diff, grid_range)
        logger.info(f"Grid bot subscribed to channels: [{price_diff}], [{grid_range}].")

        threading.Thread(
            target=handle_grid_flow,
            args=(pubsub, price_diff, grid_range, hedge_symbol), daemon=True
        ).start()
        def _on_order_update(update):
            with state.state_lock:
                state.placing_order_state.update({k: v for k, v in update.items() if k != 'status_changed'})
                if update['status_changed']:
                    state.force_fetch = True

        threading.Thread(
            target=watch_user_data_stream,
            args=(primary_symbol,),
            kwargs={'on_order_update': _on_order_update},
            daemon=True,
        ).start()
        logger.info("Grid Bot thread started and running in background.")
    except Exception as e:
        logger.error(f"Error while syncing grid montinor: {e}", exc_info=True)
