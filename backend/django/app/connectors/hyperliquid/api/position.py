import os
import logging
import asyncio
import json
from dotenv import load_dotenv
from datetime import datetime
from app.utils.redis_client import get_redis_connection
from app.utils.constants import LOCAL_TZ

from hyperliquid.info import Info
from hyperliquid.utils import constants

load_dotenv()
logger = logging.getLogger(__name__)
redis_conn = get_redis_connection()

# API_KEY_HYPERLIQUID holds the public account (wallet) address used to query
# on-chain state; API_SECRET_HYPERLIQUID (the signing key) is only needed for
# trading, so it is not referenced here.
BASE_URL = os.getenv("HYPERLIQUID_BASE_URL", constants.MAINNET_API_URL)
ACCOUNT_ADDRESS = os.environ.get("API_KEY_HYPERLIQUID")

info = Info(BASE_URL, skip_ws=True)


def _build_position_data(position: dict, mark_price):
    """Normalize a Hyperliquid position into the shared position schema.

    Mirrors the shape produced by the Binance/Bybit connectors so downstream
    consumers see identical keys regardless of exchange. Hyperliquid encodes
    direction in the sign of ``szi`` (positive = long, negative = short).
    """
    szi = float(position.get("szi", 0))
    return {
        "symbol": position.get("coin"),
        "positionAmt": position.get("szi"),
        "entryPrice": position.get("entryPx"),
        "markPrice": mark_price,
        "unRealizedProfit": position.get("unrealizedPnl"),
        "side": "Buy" if szi > 0 else "Sell",
        "updateTime": datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
    }


def fetch_position_from_api(symbol: str):
    """Force-fetch position directly from the Hyperliquid API and refresh Redis.

    Returns the normalized position dict, or None when the account holds no
    open position for ``symbol`` (in which case the stale Redis key is cleared).
    """
    try:
        user_state = info.user_state(ACCOUNT_ADDRESS)
        redis_key = f"position:hyperliquid:{symbol}"

        open_position = next(
            (
                ap["position"]
                for ap in user_state.get("assetPositions", [])
                if ap.get("position", {}).get("coin") == symbol
                and float(ap.get("position", {}).get("szi", 0)) != 0
            ),
            None,
        )

        if not open_position:
            if redis_conn.exists(redis_key):
                redis_conn.delete(redis_key)
            return None

        # user_state carries no per-position mark price; all_mids gives the
        # current mid for every coin in a single call.
        mids = info.all_mids()
        position_data = _build_position_data(open_position, mids.get(symbol))

        payload = json.dumps(position_data)
        redis_conn.set(redis_key, payload)
        redis_conn.publish(redis_key, payload)
        redis_conn.expire(redis_key, 10)
        logger.debug(f"[Position] Force-fetched from API: {symbol} positionAmt={position_data.get('positionAmt')}")
        return position_data
    except Exception as e:
        logger.error(f"Force-fetch position error for {symbol}: {e}")
        return None


async def subscribe_position_information(symbol: str):
    logger.info(f"Starting hyperliquid position subscription for {symbol}.")
    while True:
        try:
            fetch_position_from_api(symbol)
            await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            logger.error(f"Position task for {symbol} cancelled.")
            break
        except Exception as e:
            logger.error(f"Position information subscription error for {symbol}: {e}. Retrying in 1 second...")
            await asyncio.sleep(1)


def get_position(symbol: str, force: bool = False):
    if force:
        return fetch_position_from_api(symbol)
    redis_key = f"position:hyperliquid:{symbol}"
    position_data = redis_conn.get(redis_key)
    if position_data:
        return json.loads(position_data)
    return None
