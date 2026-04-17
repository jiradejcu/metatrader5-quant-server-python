import logging
import os
import sys
import time
import threading
from flask import Flask
from dotenv import load_dotenv
import MetaTrader5 as mt5
from flasgger import Swagger
from werkzeug.middleware.proxy_fix import ProxyFix
from swagger import swagger_config

# Import routes
from routes.health import health_bp
from routes.symbol import symbol_bp
from routes.data import data_bp
from routes.position import position_bp
from routes.order import order_bp
from routes.history import history_bp
from routes.error import error_bp
from routes.withdraw import withdraw_bp
import state

load_dotenv()

LOG_LEVEL = logging.INFO
LOG_FORMAT = '%(asctime)s [%(levelname)s] (%(name)s): %(message)s'

logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['PREFERRED_URL_SCHEME'] = 'https'

swagger = Swagger(app, config=swagger_config)

app.register_blueprint(health_bp)
app.register_blueprint(symbol_bp)
app.register_blueprint(data_bp)
app.register_blueprint(position_bp)
app.register_blueprint(order_bp)
app.register_blueprint(history_bp)
app.register_blueprint(error_bp)
app.register_blueprint(withdraw_bp)

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# ---------------------------------------------------------------------------
# MT5 connection helper
# ---------------------------------------------------------------------------

POLL_INTERVAL = 0.5  # seconds between background polls


def _ensure_connected() -> bool:
    """Check MT5 connection and reconnect if needed. Must be called with mt5_lock held."""
    if mt5.terminal_info() is not None:
        return True
    logger.warning("MT5 connection lost — attempting reconnect...")
    mt5.shutdown()
    time.sleep(1)
    if mt5.initialize():
        logger.info("MT5 reconnected successfully.")
        return True
    logger.error(f"MT5 reconnect failed: {mt5.last_error()}")
    return False


# ---------------------------------------------------------------------------
# Background poll thread
# ---------------------------------------------------------------------------

def _poll_loop():
    """
    Runs forever in a daemon thread. Acquires mt5_lock for each poll cycle so
    order routes cannot interleave MT5 calls. Updates the shared cache; the
    watchdog fires if this stops making progress.
    """
    logger.info("MT5 background poll thread started.")
    while True:
        try:
            with state.mt5_lock:
                if not _ensure_connected():
                    time.sleep(5)
                    continue

                # --- positions ---
                total = mt5.positions_total()
                if total is not None:
                    if total > 0:
                        raw = mt5.positions_get()
                        positions = [p._asdict() for p in raw] if raw else []
                    else:
                        positions = []
                    state.update_positions(positions)

                # --- ticks for every registered symbol ---
                for symbol in state.get_poll_symbols():
                    tick = mt5.symbol_info_tick(symbol)
                    if tick is not None:
                        state.update_tick(symbol, tick._asdict())

        except Exception:
            logger.exception("Unhandled error in MT5 poll loop")

        time.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Watchdog thread
# ---------------------------------------------------------------------------

def _watchdog_loop():
    """
    Exits the process when the background poll has not made progress for
    WATCHDOG_TIMEOUT seconds. The shell restart loop (07-start-wine-flask.sh)
    brings Flask back up within 5 seconds.
    """
    time.sleep(10)  # startup grace period
    logger.info("Watchdog started.")
    while True:
        time.sleep(5)
        age = state.poll_age()
        if age > state.WATCHDOG_TIMEOUT:
            logger.error(
                f"MT5 polling stalled for {age:.0f}s "
                f"(threshold={state.WATCHDOG_TIMEOUT:.0f}s) — exiting for restart."
            )
            os._exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if not mt5.initialize():
        logger.error(f"Failed to initialize MT5: {mt5.last_error()}")
        sys.exit(1)
    logger.info("MT5 initialized.")

    threading.Thread(target=_poll_loop, daemon=True, name="mt5-poll").start()
    threading.Thread(target=_watchdog_loop, daemon=True, name="watchdog").start()

    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('MT5_API_PORT')),
        threaded=True,
    )
