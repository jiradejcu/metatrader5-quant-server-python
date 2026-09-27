import json

import os
import time
import logging
import threading
from . import config
from decimal import Decimal
from app.utils.redis_client import get_redis_connection
from app.utils.api.positions import get_position_by_symbol as get_hedge_position
from app.utils.api.positions import get_net_position, PositionsUnavailable
from app.utils.api.order import send_market_order, validate_order
from app.utils.position_group import update_position_group, resolve_group_id, make_comment, get_position_group, seed_position_group
from ..trading_sessions import is_within_trading_session

logger = logging.getLogger(__name__)

pre_order_volume = None
_consecutive_errors = 0
_ERROR_THRESHOLD = 3
_POSITION_SYNC_OK_FLAG = "position_sync_ok_flag"
_SYNC_PENDING_FLAG = "sync_pending_flag"
# OK flag is a liveness heartbeat: its absence means the sync process is dead.
# Pending TTL must be >= OK TTL so the in-flight lock never lapses while the grid
# bot is still running _process_tick (which is gated on the OK flag) — otherwise a
# new entry could be placed on top of an unconfirmed hedge.
_OK_FLAG_TTL = 2
_SYNC_PENDING_TTL = 5

# ── Recovery mode ────────────────────────────────────────────────────────────
# Entered when a hedge market order is rejected because of market conditions
# (thin liquidity, requotes, no quotes, ...) rather than for a known reason
# (outside trading session, not enough money, trading disabled, MT5 down).
# While the flag is set:
#   * position_sync stops hedging the discrepancy and instead probes the market
#     with a minimum-volume order every _RECOVERY_PROBE_INTERVAL_S; the first
#     probe that fills clears the flag and normal syncing resumes.
#   * grid_bot cancels its open orders and moves the primary position to match
#     the hedge (see grid_bot._process_recovery_tick).
# No TTL: the flag must survive a position_sync restart so recovery resumes.
_RECOVERY_FLAG = "grid_bot_recovery_flag"
_RECOVERY_PROBE_INTERVAL_S = float(os.getenv('RECOVERY_PROBE_INTERVAL_S', '10'))
_last_probe_ts = 0.0

# MT5 TRADE_RETCODE_* values that mean "the market couldn't take the order
# right now" — the order itself was fine.
_MARKET_CONDITION_RETCODES = {
    10004,  # REQUOTE
    10006,  # REJECT (broker/LP rejected — typically no liquidity)
    10010,  # DONE_PARTIAL (only part of the volume was available)
    10012,  # TIMEOUT
    10015,  # INVALID_PRICE (price moved away)
    10020,  # PRICE_CHANGED
    10021,  # PRICE_OFF (no quotes)
}
# validate_order checks whose failure points to a known, non-market cause.
_NON_MARKET_CHECKS = {
    "terminal_connected",
    "algo_trading_enabled",
    "account_trade_allowed",
    "symbol_trading_enabled",
    "tick_fresh",  # stale tick == market closed
}


def _log_entry_price_diff(redis_conn, hedge_symbol: str, primary_entry: float, trigger: str):
    group = get_position_group(redis_conn, hedge_symbol)
    hedge_entry = float(group["entry_price"]) if group else 0.0
    if primary_entry == 0 or hedge_entry == 0:
        return
    diff = primary_entry - hedge_entry
    diff_pct = diff / hedge_entry * 100
    logger.info(
        "[EntryPriceDiff][%s] primary_entry=%.5f hedge_entry=%.5f diff=%.5f (%.3f%%)",
        trigger, primary_entry, hedge_entry, diff, diff_pct,
    )

def _mark_sync_healthy(redis_conn):
    global _consecutive_errors
    if _consecutive_errors > 0:
        logger.info("[PositionSync] Recovered — restoring ok flag.")
        _consecutive_errors = 0
    redis_conn.set(_POSITION_SYNC_OK_FLAG, "1", ex=_OK_FLAG_TTL)


def _stop_grid_bot(reason: str):
    try:
        redis_conn = get_redis_connection()
        redis_conn.delete(_POSITION_SYNC_OK_FLAG)
        redis_conn.delete("grid_bot_enabled_flag")
        logger.error("[PositionSync] Stopping grid bot: %s", reason)
    except Exception:
        pass


def is_in_recovery(redis_conn) -> bool:
    return redis_conn.get(_RECOVERY_FLAG) is not None


def _enter_recovery(redis_conn, reason: str):
    global _last_probe_ts
    if not is_in_recovery(redis_conn):
        logger.error("[PositionSync] Entering recovery mode: %s", reason)
    redis_conn.set(_RECOVERY_FLAG, json.dumps({"reason": reason, "since": time.time()}))
    # Wait a full interval before the first probe — the order was just rejected.
    _last_probe_ts = time.monotonic()


def _exit_recovery(redis_conn, reason: str):
    if is_in_recovery(redis_conn):
        logger.info("[PositionSync] Exiting recovery mode: %s", reason)
    redis_conn.delete(_RECOVERY_FLAG)


def _is_market_condition_failure(error, hedge_symbol, side, volume):
    """Decide whether a failed hedge order was rejected purely because of
    market conditions. Returns (is_market_condition, reason).

    Recovery mode is only for failures with no better explanation, so every
    known cause is ruled out first: outside the trading session, a retcode
    that names another cause (no money, market closed, ...), transport errors
    with no retcode, and finally a validate_order dry-run of the same order
    (catches no margin / closed market / trading disabled hidden behind a
    generic reject).
    """
    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    primary_symbol = config.PAIRS[PAIR_INDEX]['primary']['symbol']
    retcode = (error or {}).get('retcode')
    comment = (error or {}).get('comment')

    if not is_within_trading_session(primary_symbol, hedge_symbol):
        return False, f"outside trading session (retcode={retcode}: {comment})"

    if retcode not in _MARKET_CONDITION_RETCODES:
        return False, f"retcode={retcode}: {comment}"

    check = validate_order(symbol=hedge_symbol, order_type=side, volume=float(volume))
    check_retcode = check.get('retcode')
    if check_retcode is not None and check_retcode not in (0, 10009) and check_retcode not in _MARKET_CONDITION_RETCODES:
        return False, f"dry-run retcode={check_retcode}: {check.get('comment')}"
    non_market_checks = [c for c in check.get('failed_checks', []) if c in _NON_MARKET_CHECKS]
    if non_market_checks:
        return False, f"dry-run failed {non_market_checks}: {check.get('comment')}"

    return True, f"retcode={retcode}: {comment}"


def _handle_order_failure(redis_conn, error, hedge_symbol, side, volume):
    is_market, reason = _is_market_condition_failure(error, hedge_symbol, side, volume)
    if is_market:
        _enter_recovery(redis_conn, f"hedge order rejected by market conditions ({reason})")
        # Handled, and the sync process is alive — keep the heartbeat so grid_bot
        # picks up recovery on its next tick instead of reading "sync failed".
        _mark_sync_healthy(redis_conn)
    else:
        _exit_recovery(redis_conn, "non-market failure, stopping grid bot instead")
        _stop_grid_bot(f"market order failed for {hedge_symbol} ({reason})")


def _probe_volume():
    """Smallest hedge order, in lots (e.g. 1 / 100 = 0.01 lot for XAUUSD)."""
    pair = config.PAIRS[int(os.getenv('PAIR_INDEX'))]
    return Decimal(str(pair['minimum_trade_amount'])) / Decimal(pair['contract_size'])


def _probe_side(discrepancy, hedge_volume, contract_size):
    """Pick the probe direction so the probe does useful work: close the
    outstanding discrepancy if there is one, otherwise shrink the hedge
    position. grid_bot (in recovery) follows the hedge, so either way the
    primary is re-matched afterwards.
    """
    if abs(discrepancy) >= _probe_volume() * contract_size:
        return 'BUY' if discrepancy < 0 else 'SELL'
    return 'SELL' if hedge_volume > 0 else 'BUY'


def _mark_sync_error():
    global _consecutive_errors
    _consecutive_errors += 1
    logger.warning("[PositionSync] Consecutive errors: %d/%d", _consecutive_errors, _ERROR_THRESHOLD)
    if _consecutive_errors >= _ERROR_THRESHOLD:
        _stop_grid_bot(f"{_consecutive_errors} consecutive errors")


def _record_fill(redis_conn, order, sign, hedge_symbol, group_id, primary_entry_price):
    fill_price = float(order.get('price', 0))
    fill_volume = abs(float(order.get('volume', 0)))

    if fill_price > 0 and fill_volume > 0:
        update_position_group(
            redis_conn=redis_conn,
            symbol=hedge_symbol,
            fill_price=fill_price,
            fill_volume=sign * fill_volume,
            group_id=group_id,
        )
        _log_entry_price_diff(redis_conn, hedge_symbol, float(primary_entry_price), "hedge_fill")


def _arm_confirmation(redis_conn, hedge_volume, hedge_symbol):
    """Call straight after a hedge order fills, before any other bookkeeping.

    pre_order_volume is set first because it lives in memory and can't fail:
    from here on every pass waits for MT5 to report a changed hedge volume
    before hedging again. If a Redis call below (or in _record_fill) raises, the
    guard is already armed, so a stale cached hedge position can't trigger the
    same hedge order a second time.
    """
    global pre_order_volume
    pre_order_volume = hedge_volume
    redis_conn.set(_SYNC_PENDING_FLAG, "1", ex=_SYNC_PENDING_TTL)
    redis_conn.delete(f"position:mt5:{hedge_symbol}")


def handle_position_update(pubsub):
    global pre_order_volume, _last_probe_ts
    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    primary_exchange = config.PAIRS[PAIR_INDEX]['primary']['exchange']
    hedge_exchange = config.PAIRS[PAIR_INDEX]['hedge']['exchange']
    contract_size = Decimal(config.PAIRS[PAIR_INDEX]['contract_size'])
    for message in pubsub.listen():
        try:
            redis_conn = get_redis_connection()
            if message['type'] == 'message' and redis_conn.get("position_sync_paused_flag") is None:
                position_data = json.loads(message['data'])
                received_symbol = position_data.get('symbol')
                primary_symbol = config.PAIRS[PAIR_INDEX]['primary']['symbol']
                if received_symbol != primary_symbol:
                    logger.debug(f"Ignoring position update for symbol {received_symbol}. Expected {primary_symbol}.")
                    continue
                position_amt = Decimal(str(position_data.get('positionAmt', '0')))
                if os.getenv('MOCK_ENTRY_POSITION_AMT', 'false').lower() == 'true':
                    position_amt *= contract_size
                primary_entry_price = Decimal(str(position_data.get('entryPrice', '0')))
                primary_mark_price = Decimal(str(position_data.get('markPrice') or '0'))
                primary_time_update = position_data.get('updateTime', None)

                logger.debug(
                    f"Primary Position {primary_exchange}:{primary_symbol} - "
                    f"Amount: {position_amt}, Entry Price: {primary_entry_price}, Mark Price: {primary_mark_price}, Update Time: {primary_time_update}"
                )

                hedge_symbol = config.PAIRS[PAIR_INDEX]['hedge']['symbol']

                hedge_position = get_hedge_position(hedge_symbol)
                hedge_volume = Decimal(str(hedge_position.get('volume', '0')))
                hedge_entry_price = Decimal(str(hedge_position.get('entryPrice', '0')))
                hedge_mark_price = Decimal(str(hedge_position.get('markPrice', '0')))
                hedge_time_update = hedge_position.get('time_update', None)

                if pre_order_volume is not None:
                    if hedge_volume == pre_order_volume:
                        logger.debug(f"Hedge volume unchanged at {hedge_volume}. Waiting for MT5 position update...")
                        # Heartbeat: the process is alive and healthily waiting for the hedge
                        # confirmation. Keep OK (liveness) and pending (in-flight) fresh so the
                        # grid bot reads this as "mid-hedge-wait" — block new entries but keep
                        # managing existing orders — rather than "sync process failed".
                        _mark_sync_healthy(redis_conn)
                        redis_conn.set(_SYNC_PENDING_FLAG, "1", ex=_SYNC_PENDING_TTL)
                        continue
                    logger.debug(f"MT5 position confirmed: {pre_order_volume} → {hedge_volume}.")
                    pre_order_volume = None
                    redis_conn.delete(f"position:mt5:{hedge_symbol}")
                    redis_conn.delete(_SYNC_PENDING_FLAG)
                    continue

                logger.debug(
                    f"Hedge Position {hedge_exchange}:{hedge_symbol} - "
                    f"Volume: {hedge_volume}, Entry Price: {hedge_entry_price}, "
                    f"Mark Price: {hedge_mark_price}, Time Update: {hedge_time_update}"
                )

                discrepancy = position_amt + hedge_volume * contract_size

                logger.debug(
                    f"Primary Amount: {position_amt}, Hedge Volume: {hedge_volume}. "
                    f"Position Size Difference: {discrepancy}."
                )

                order_amt = Decimal(int(-discrepancy))

                if is_in_recovery(redis_conn):
                    # grid_bot owns the discrepancy now (it moves the primary to the
                    # hedge) — don't fight it. Just probe until the market takes orders.
                    _mark_sync_healthy(redis_conn)
                    if time.monotonic() - _last_probe_ts < _RECOVERY_PROBE_INTERVAL_S:
                        continue
                    _last_probe_ts = time.monotonic()
                    probe_side = _probe_side(discrepancy, hedge_volume, contract_size)
                    probe_volume = _probe_volume()
                    logger.info(f"[PositionSync][Recovery] Probing market: {probe_side} {probe_volume} {hedge_symbol}")
                    group_id = resolve_group_id(redis_conn=redis_conn, symbol=hedge_symbol)
                    order, error = send_market_order(
                        symbol=hedge_symbol,
                        volume=probe_volume,
                        order_type=probe_side,
                        comment=make_comment(group_id),
                    )
                    if not order:
                        # Still bad (stay in recovery) or turned into a known failure (stop).
                        _handle_order_failure(redis_conn, error, hedge_symbol, probe_side, probe_volume)
                        continue
                    _arm_confirmation(redis_conn, hedge_volume, hedge_symbol)
                    _exit_recovery(redis_conn, f"probe {probe_side} {probe_volume} filled")
                    _record_fill(redis_conn, order, 1 if probe_side == 'BUY' else -1,
                                 hedge_symbol, group_id, primary_entry_price)
                    continue

                if abs(order_amt) >= Decimal('1.00'):
                    logger.info(
                        f"Discrepancy detected for {received_symbol}. "
                        f"Placing order to adjust by {order_amt}."
                    )

                    order_volume = order_amt / contract_size

                    group_id = resolve_group_id(
                        redis_conn=redis_conn,
                        symbol=hedge_symbol,
                    )

                    order_side = 'BUY' if order_amt > 0 else 'SELL'
                    order, error = send_market_order(
                        symbol=hedge_symbol,
                        volume=abs(order_volume),
                        order_type=order_side,
                        comment=make_comment(group_id),  # survives Redis restarts
                    )

                    if not order:
                        _handle_order_failure(redis_conn, error, hedge_symbol, order_side, abs(order_volume))
                        continue

                    _arm_confirmation(redis_conn, hedge_volume, hedge_symbol)
                    _record_fill(redis_conn, order, 1 if order_amt > 0 else -1,
                                 hedge_symbol, group_id, primary_entry_price)
                else:
                    logger.debug(f"No significant discrepancy for {received_symbol}. No action taken.")

                _mark_sync_healthy(redis_conn)

        except PositionsUnavailable as e:
            # Can't read the hedge, so we can't size a hedge order. Skip this pass
            # without counting it as an error and without a heartbeat: grid_bot
            # idles once the ok flag lapses, and resumes when MT5 answers again.
            logger.warning(f"[PositionSync] Hedge position unavailable, skipping update: {e}")
        except Exception as e:
            logger.error(f"Error processing position update: {e}", exc_info=True)
            _mark_sync_error()

def start_position_sync():
    if os.environ.get('RUN_MAIN') != 'true':
        return

    PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
    primary_exchange = config.PAIRS[PAIR_INDEX]['primary']['exchange']
    primary_symbol = config.PAIRS[PAIR_INDEX]['primary']['symbol']
    logger.info(f"Starting position sync for {primary_symbol}...")

    try:
        redis_conn = get_redis_connection()

        # Anchor the position-group baseline to the live MT5 hedge position before
        # processing any updates. Otherwise the group assumes a flat start and any
        # position already open is orphaned, leaving a permanent volume offset that
        # the incremental fill accounting never corrects.
        hedge_symbol = config.PAIRS[PAIR_INDEX]['hedge']['symbol']
        try:
            live = get_net_position(hedge_symbol)
            seed_position_group(redis_conn, hedge_symbol, live['volume'], live['entryPrice'])
        except Exception as e:
            logger.error(f"Failed to seed position group from MT5 for {hedge_symbol}: {e}", exc_info=True)

        pubsub = redis_conn.pubsub()
        pubsub.subscribe(f"position:{primary_exchange}:{primary_symbol}")
        logger.info(f"Subscribed to Redis channel position:{primary_exchange}:{primary_symbol} for position updates.")
        threading.Thread(target=handle_position_update, args=(pubsub,), daemon=True).start()
    except Exception as e:
        logger.error(f"Error while syncing position for {primary_symbol}: {e}", exc_info=True)
