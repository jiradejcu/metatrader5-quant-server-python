import logging
import os
import threading
import time

from app.utils.redis_client import get_redis_connection
from . import config

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 30       # seconds between each health check
STARTUP_GRACE = 30        # seconds to wait before first check (allow subs to come up)


def _check_loop(entry_exchange: str, entry_symbol: str, hedge_symbol: str):
    keys = {
        f"ticker:{entry_exchange}:{entry_symbol}": f"{entry_exchange} ticker ({entry_symbol})",
        f"ticker:mt5:{hedge_symbol}":              f"mt5 ticker ({hedge_symbol})",
        f"position:{entry_exchange}:{entry_symbol}": f"{entry_exchange} position ({entry_symbol})",
        f"position:mt5:{hedge_symbol}":             f"mt5 position ({hedge_symbol})",
        f"spread:{entry_exchange}:{entry_symbol}":  f"spread feed ({entry_exchange}:{entry_symbol})",
    }

    redis_conn = get_redis_connection()
    previously_unhealthy: set = set()

    time.sleep(STARTUP_GRACE)
    logger.info("Subscription health monitor active.")

    while True:
        unhealthy = {key for key in keys if not redis_conn.exists(key)}

        # Log newly unhealthy subscriptions
        newly_unhealthy = unhealthy - previously_unhealthy
        for key in newly_unhealthy:
            logger.warning(f"SUBSCRIPTION UNHEALTHY: {keys[key]} [{key}] — no data in Redis.")

        # Log recoveries
        recovered = previously_unhealthy - unhealthy
        for key in recovered:
            logger.info(f"SUBSCRIPTION RECOVERED: {keys[key]} [{key}].")

        # If still unhealthy, repeat the warning each cycle so it's visible in tailing logs
        still_unhealthy = unhealthy & previously_unhealthy
        if still_unhealthy:
            labels = ", ".join(keys[k] for k in still_unhealthy)
            logger.warning(f"SUBSCRIPTIONS STILL UNHEALTHY: {labels}.")

        if not unhealthy:
            logger.info("Health monitor OK — all subscriptions healthy.")

        previously_unhealthy = unhealthy
        time.sleep(CHECK_INTERVAL)


def start_health_monitor():
    if os.environ.get('RUN_MAIN') != 'true':
        return

    try:
        pair_index_env = os.getenv('PAIR_INDEX')
        if pair_index_env is None:
            logger.warning("Health monitor: PAIR_INDEX not set, skipping.")
            return

        pair = config.PAIRS[int(pair_index_env)]
        entry_exchange = pair['entry']['exchange']
        entry_symbol = pair['entry']['symbol']
        hedge_symbol = pair['hedge']['symbol']

        threading.Thread(
            target=_check_loop,
            args=(entry_exchange, entry_symbol, hedge_symbol),
            daemon=True,
            name="subscription-health-monitor",
        ).start()
        logger.info(
            f"Subscription health monitor started "
            f"(grace={STARTUP_GRACE}s, interval={CHECK_INTERVAL}s)."
        )
    except Exception as e:
        logger.error(f"Failed to start subscription health monitor: {e}")
