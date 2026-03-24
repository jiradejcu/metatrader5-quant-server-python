import os
import logging
import asyncio
import pandas as pd
import json
from app.utils.redis_client import get_redis_connection
from app.utils.api.data import symbol_info_tick
from dotenv import load_dotenv
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL,
    ConfigurationWebSocketAPI,
)

import json

def prepare_json(json_str, default_value):
    if json_str == None:
            return default_value
    return json.loads(json_str)

def clean_val(val):
    if isinstance(val, bytes):
        val = val.decode('utf-8')
    try:
        return float(val) if val is not None else 0.0
    except (ValueError, TypeError):
        return 0.0

load_dotenv()
logger = logging.getLogger(__name__)

configuration_ws_api = ConfigurationWebSocketAPI(
    api_key=os.environ.get('API_KEY_BINANCE'),
    api_secret=os.environ.get('API_SECRET_BINANCE'),
    stream_url=os.getenv(
        "STREAM_URL", DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL
    ),
)

client = DerivativesTradingUsdsFutures(config_ws_api=configuration_ws_api)
redis_conn = get_redis_connection()

class json_encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return json.JSONEncoder.default(self, obj)

async def subscribe_position_information(symbol: str):
    while True:
        connection = None
        try:
            connection = await client.websocket_api.create_connection()
            logger.info(f"WebSocket connection for {symbol} position information established.")

            while True:
                response = await connection.position_information()

                # rate_limits = response.rate_limits
                # logger.debug(f"Position information rate limits: {rate_limits}")

                positions_list = response.data().result
                positions_as_dicts = [p.to_dict() for p in positions_list]
                df = pd.DataFrame(positions_as_dicts)

                df['positionAmt'] = pd.to_numeric(df['positionAmt'])
                symbol_open_position_df = df[(df['symbol'] == symbol)]

                redis_key = f"position:binance:{symbol}"

                if not symbol_open_position_df.empty:
                    position_data = symbol_open_position_df.iloc[0].to_dict()
                    
                    thailand_tz = timezone(timedelta(hours=7))
                    latest_update = datetime.now(thailand_tz).strftime("%Y-%m-%d %H:%M:%S")
                    position_data['updateTime'] = latest_update
                    
                    # Save data into redis
                    redis_conn.set(redis_key, json.dumps(position_data))
                    redis_conn.publish(redis_key, json.dumps(position_data))
                    redis_conn.expire(redis_key, 10)

                    # logger.debug(f"Updated Redis {redis_key} -> {position_data['positionAmt']}")
                else:
                    if redis_conn.exists(redis_key):
                        redis_conn.delete(redis_key)
                        # logger.debug(f"Deleted Redis key {redis_key} as no position data found for {symbol}.")

                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.error(f"WebSocket task for {symbol} position cancelled. Closing connection.")
            break
        except Exception as e:
            logger.error(f"Position information subscription error for {symbol}: {e}. Retrying in 1 seconds...")
            await asyncio.sleep(1)
        finally:
            if connection:
                try:
                    logger.warning(f"Closing WebSocket connection for {symbol} position information...")
                    await connection.close_connection(close_session=True)
                except Exception as close_err:
                    logger.warning(f"Error while closing connection for {symbol}: {close_err}")


async def subscribe_spread_diff(binance_symbol: str, mt5_symbol: str):
    while True:
        try:
            ticker_binance_key = f"ticker:{binance_symbol}"
            ticker_mt5_key = f"ticker (MT5):{mt5_symbol}"

            raw_ticker_binance = redis_conn.hgetall(ticker_binance_key)
            ticker_binance = raw_ticker_binance if raw_ticker_binance else {}
            ticker_mt5 = prepare_json(redis_conn.get(ticker_mt5_key), {})

            binance_best_bid = clean_val(ticker_binance.get(b'best_bid' if b'best_bid' in ticker_binance else 'best_bid'))
            binance_best_ask = clean_val(ticker_binance.get(b'best_ask' if b'best_ask' in ticker_binance else 'best_ask'))
            mt5_best_bid = clean_val(ticker_mt5.get('best_bid'))
            mt5_best_ask = clean_val(ticker_mt5.get('best_ask'))

            # Upper diff : BN_best_ask - MT5_buy
            # Lower diff : BN_best_bid - MT5_sell
            current_upper_diff = round(binance_best_ask - mt5_best_bid,2)
            current_lower_diff = round(binance_best_bid - mt5_best_ask,2)

            grid_bot_boundary_key = f"place order of {binance_symbol}"
            redis_conn.set(grid_bot_boundary_key, json.dumps({
                            "current_upper_diff": current_upper_diff,
                            "current_lower_diff": current_lower_diff,
                        }))
            redis_conn.publish(grid_bot_boundary_key, json.dumps({
                "current_upper_diff": current_upper_diff,
                "current_lower_diff": current_lower_diff,
            }))
            redis_conn.expire(grid_bot_boundary_key, 10)

            await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.error(f"Spread diff task for {binance_symbol}/{mt5_symbol} cancelled.")
            break
        except Exception as e:
            logger.error(f"Spread diff error for {binance_symbol}/{mt5_symbol}: {e}. Retrying in 1 seconds...")
            await asyncio.sleep(1)


def get_position(symbol: str):
    redis_key = f"position:binance:{symbol}"
    position_data = redis_conn.get(redis_key)
    if position_data:
        return json.loads(position_data)
    return None