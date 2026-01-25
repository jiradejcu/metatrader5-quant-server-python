import os
import logging
import asyncio
import pandas as pd
import json
from app.utils.redis_client import get_redis_connection
from app.utils.api.positions import get_positions as get_mt5_position
from app.utils.api.data import symbol_info_tick
from dotenv import load_dotenv
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL,
    ConfigurationWebSocketAPI,
)

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
    connection = None
    try:
        connection = await client.websocket_api.create_connection()
        logger.info("WebSocket connection for position information established.")

        while True:
            response = await connection.position_information()

            rate_limits = response.rate_limits
            logger.debug(f"Position information rate limits: {rate_limits}")

            positions_list = response.data().result
            positions_as_dicts = [p.to_dict() for p in positions_list]
            df = pd.DataFrame(positions_as_dicts)

            relevant_columns = [
                'symbol',
                'positionAmt',
                'entryPrice',
                'markPrice',
                'unRealizedProfit',
                'leverage',
                'liquidationPrice',
            ]
           

            df['positionAmt'] = pd.to_numeric(df['positionAmt'])
            symbol_open_position_df = df[(df['symbol'] == symbol)]

            redis_key = f"position:{symbol}"

            if not symbol_open_position_df.empty:
                # logger.debug(symbol_open_position_df[relevant_columns].to_json(orient='records'))            
                position_data = symbol_open_position_df.iloc[0].to_dict()
                
                thailand_tz = timezone(timedelta(hours=7))
                latest_update = datetime.now(thailand_tz).strftime("%Y-%m-%d %H:%M:%S")
                position_data['updateTime'] = latest_update
                
                # Save data into redis
                redis_conn.set(redis_key, json.dumps(position_data))
                redis_conn.publish(redis_key, json.dumps(position_data))
                redis_conn.expire(redis_key, 10)

                logger.debug(f"Updated Redis {redis_key} -> {position_data['positionAmt']}")
            else:
                if redis_conn.exists(redis_key):
                    redis_conn.delete(redis_key)
                    logger.debug(f"Deleted Redis key {redis_key} as no position data found for {symbol}.")

            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info("WebSocket task cancelled. Closing connection.")
    except Exception as e:
        logger.error(f"Position information subscription error: {e}")
    finally:
        if connection:
            logger.info("Closing WebSocket connection...")
            await connection.close_connection(close_session=True)

async def subscribe_position_mt5_information(symbol: str):
    try:
        while True:
            mt5_symbol = symbol
            # todo: if user has two symbols, we must write more code to filter using only mt5_symbol attribute
            # add map filter position.symbol to select only match with mt5_symbol, now considering all
            positions = get_mt5_position()
            positions = positions[positions['symbol'] == mt5_symbol]
            redis_key = f"position: {mt5_symbol}"

            if redis_conn.exists(redis_key):
                redis_conn.delete(redis_key)
                logger.debug(f"Delete Redis key {redis_key} as no position data found for {symbol}.")
            
            now = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S") # use UTC(+7) Thailand time zone
            result = {
                "time_update": now,
                "entryPrice": "0",
                "markPrice": "0",
                "unRealizedProfit": "0",
                "positionAmt": "0"
            }

            tick = symbol_info_tick(mt5_symbol)
            mark_price = 0

            if tick is not None and not tick.empty:
                try:
                    ask = float(tick['ask'].iloc[0]) if 'ask' in tick else 0
                    bid = float(tick['bid'].iloc[0]) if 'bid' in tick else 0
                except (AttributeError, KeyError, TypeError):
                    ask = getattr(tick, 'ask', 0)
                    bid = getattr(tick, 'bid', 0)
                # todo refactor and if this logic is wrong, fixing it
                mark_price = ask
                result["markPrice"] = mark_price

            if not positions.empty:
                # Handling logic before calculating average
                positions['cal_type'] = positions['type'].apply(lambda x: -1 if x == 1 else 1)
                positions['cal_volume'] = positions['volume'] * positions['cal_type']
                
                total_volume = float(positions['cal_volume'].sum())
                # todo handle case when fully hedging working and you add one more position without closing fully hedge (MT5)
                weighted_entry = float((positions['price_open'] * positions['cal_volume']).sum() / positions['cal_volume'].sum()) if total_volume != 0.0 else 0
                total_profit = 0 if total_volume == 0.0 else float(positions['profit'].sum())
                mark_price = float(ask if total_volume < 0 else bid)
                
                logger.debug(f"Set new data for {redis_key}")

                result["entryPrice"] = f"{weighted_entry:.3f}"
                result["markPrice"] = f"{mark_price:.3f}"
                result["unRealizedProfit"] = f"{total_profit:.2f}"
                result["positionAmt"] = f"{total_volume:.3f}"

            # Save data into redis
            data = json.dumps(result, cls=json_encoder)
            redis_conn.set(redis_key, data)
            redis_conn.publish(redis_key, data)
            redis_conn.expire(redis_key, 10)

            logger.debug(f"Updated Redis {redis_key} success")
                
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.info("websocket task cancelled. Closing connection.")
    except Exception as e:
        logger.error(f"Position information subscription error: {e}")


def get_position(symbol: str):
    redis_key = f"position:{symbol}"
    position_data = redis_conn.get(redis_key)
    if position_data:
        return json.loads(position_data)
    return None