# backend/django/app/quant/algorithms/mean_reversion/entry.py

import pandas as pd
import requests
import logging
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import traceback

from app.utils.arithmetics import calculate_order_capital, calculate_order_size_usd, calculate_commission, get_price_at_pnl, get_pnl_at_price, convert_usd_to_lots
from app.utils.constants import MT5Timeframe
from app.utils.api.data import fetch_data_pos, symbol_info_tick
from app.utils.api.positions import get_positions
from app.utils.api.order import send_market_order
from app.utils.constants import TIMEZONE
from app.utils.account import have_open_positions_in_symbol
from app.utils.market import is_market_open
from app.quant.indicators.mean_reversion import mean_reversion
from app.quant.algorithms.mean_reversion.config import PAIRS, MAIN_TIMEFRAME, TP_PNL_MULTIPLIER, SL_PNL_MULTIPLIER, LEVERAGE, DEVIATION, CAPITAL_PER_TRADE, TRAILING_STOP_STEPS
from app.utils.db.create import create_trade

load_dotenv()
logger = logging.getLogger(__name__)

def entry_algorithm():
    try:
        for pair in PAIRS:            
            logger.info(f"Checking {pair} for open positions.")
            if have_open_positions_in_symbol(pair):
                logger.info(f"Skipping {pair} because it has open positions.")
                continue

            if not is_market_open(pair):
                logger.info(f"Skipping {pair} because the market is not open.")
                continue
                
            df = fetch_data_pos(pair, MAIN_TIMEFRAME, 10)
            if df is None or df.empty:
                logger.info(f"Skipping {pair} because there is no data.")
                continue
            
            df['mean_reversion'] = mean_reversion(df)
            last_row = df.iloc[-2]

            tick_info = symbol_info_tick(pair)
            if tick_info is None or tick_info.empty:
                logger.info(f"Skipping {pair} because there is no tick info.")
                continue

            order_capital = CAPITAL_PER_TRADE
            order_type = 'BUY' if last_row['mean_reversion'] == 'bottom' else 'SELL'
            last_tick_price = tick_info['ask'].iloc[0] if order_type == 'BUY' else tick_info['bid'].iloc[0]
            price_decimals = len(str(last_tick_price).split('.')[-1])
            order_size_usd = calculate_order_size_usd(order_capital, LEVERAGE)
            order_volume_lots = convert_usd_to_lots(pair, order_size_usd, order_type)

            # Validate that 'order_volume_lots' is a float
            if isinstance(order_volume_lots, (pd.Series, pd.DataFrame)):
                order_volume_lots = order_volume_lots.iloc[0] if not order_volume_lots.empty else 0.0

            if order_volume_lots < 0.01:
                error_msg = f"Order volume is too low for {pair}."
                logger.error({'error_msg': error_msg, 'order_volume_lots': order_volume_lots})
                continue

            desired_sl_pnl = order_capital * SL_PNL_MULTIPLIER
            commission = calculate_commission(order_size_usd, pair)

            if last_row['mean_reversion'] in ['top', 'bottom']:
                sl_including_commission, sl_excluding_commission = get_price_at_pnl(
                    desired_pnl=desired_sl_pnl,
                    commission=commission,
                    order_size_usd=order_size_usd,
                    leverage=LEVERAGE,
                    entry_price=last_tick_price,
                    type=order_type
                )

                if order_type == 'BUY':
                    if sl_including_commission > tick_info['bid'].iloc[0]:
                        error_msg = f"SL is too high for {pair}."
                        logger.error({'error_msg': error_msg, 'sl_including_commission': sl_including_commission, 'tick_info': tick_info})
                        continue
                if order_type == 'SELL':
                    if sl_including_commission < tick_info['ask'].iloc[0]:
                        error_msg = f"SL is too low for {pair}."
                        logger.error({'error_msg': error_msg, 'sl_including_commission': sl_including_commission, 'tick_info': tick_info})
                        continue
                
                order, _ = send_market_order(
                    symbol=pair,
                    volume=order_volume_lots,
                    order_type=order_type,
                    sl=round(sl_including_commission, price_decimals),
                    deviation=DEVIATION,
                    type_filling="ORDER_FILLING_FOK",
                    position_size_usd=order_size_usd,
                    commission=commission,
                    capital=order_capital,
                    leverage=LEVERAGE
                )

                if order is not None:
                    trade_info = {
                        'event': 'trade_opened',
                        'symbol': pair,
                        'entry_condition': f"{last_row['mean_reversion'].upper()} MEAN REVERSION DETECTED",
                        'order_capital': f"${order_capital:.5f}",
                        'order_size_usd': f"${order_size_usd:.5f}",
                        'sl_pnl_multiplier': f"{SL_PNL_MULTIPLIER * 100}%",
                        'desired_sl_pnl': f"${desired_sl_pnl:.5f}",
                        'commission': f"${commission:.5f}",
                        'order_info': {
                            'order': order,  # Include the entire order response
                            'type': order_type,
                            "sl": sl_including_commission,
                        },
                        'tick_info': tick_info,
                        'sl_including_commission': {
                            'sl_including_commission': f"${sl_including_commission:.5f}",
                            'sl_price_difference_including_commission': f"${(sl_including_commission - last_tick_price):.5f}",
                            'sl_price_difference_percentage_including_commission': f"{(sl_including_commission / last_tick_price - 1) * 100:.5f}%",
                            'pnl_at_sl_including_commission': f"${get_pnl_at_price(sl_including_commission, last_tick_price, order_size_usd, LEVERAGE, order_type, commission)[1]:.5f}",
                        },
                        'sl_excluding_commission': {
                            'sl_excluding_commission': f"${sl_excluding_commission:.5f}",
                            'sl_price_difference_excluding_commission': f"${(sl_excluding_commission - last_tick_price):.5f}",
                            'sl_price_difference_percentage_excluding_commission': f"{(sl_excluding_commission / last_tick_price - 1) * 100:.5f}%",
                            'pnl_at_sl_excluding_commission': f"${get_pnl_at_price(sl_excluding_commission, last_tick_price, order_size_usd, LEVERAGE, order_type, commission)[1]:.5f}",
                        },
                    }

                    try:
                        create_trade(order, pair, order_capital, order_size_usd, 
                                     LEVERAGE, commission, order_type, 'Alpari',
                                     'FOREX', 'MEAN REVERSION', MAIN_TIMEFRAME, order_volume_lots,
                                     sl_including_commission, None)
                    except Exception as e:
                        error_msg = f"Error creating trade record in DB: {e}\n{traceback.format_exc()}"
                        logger.error(error_msg)

                    info_msg = f"Order placed successfully for {pair}"
                    logger.info(info_msg, order, trade_info)
                else:
                    trade_info = {
                        'event': 'trade_failed_to_open',
                        'entry_condition': f"{last_row['mean_reversion'].upper()} MEAN REVERSION DETECTED",
                        'symbol': pair,
                        'type': order_type,
                        'order_capital': f"${order_capital:.5f}",
                        'order_volume_lots': f"{order_volume_lots} lots",
                        'order_size_usd': f"${order_size_usd:.5f}",
                        'sl_pnl_multiplier': f"{SL_PNL_MULTIPLIER * 100}%",
                        'desired_sl_pnl': f"${desired_sl_pnl:.5f}",
                        'commission': f"${commission:.5f}",
                        'tick_info': tick_info,
                        'sl_including_commission': {
                            'sl_including_commission': f"${sl_including_commission:.5f}",
                            'sl_price_difference_including_commission': f"${(sl_including_commission - last_tick_price):.5f}",
                            'sl_price_difference_percentage_including_commission': f"{(sl_including_commission / last_tick_price - 1) * 100:.5f}%",
                            'pnl_at_sl_including_commission': f"${get_pnl_at_price(sl_including_commission, last_tick_price, order_size_usd, LEVERAGE, order_type, commission)[1]:.5f}",
                        },
                        'sl_excluding_commission': {
                            'sl_excluding_commission': f"${sl_excluding_commission:.5f}",
                            'sl_price_difference_excluding_commission': f"${(sl_excluding_commission - last_tick_price):.5f}",
                            'sl_price_difference_percentage_excluding_commission': f"{(sl_excluding_commission / last_tick_price - 1) * 100:.5f}%",
                            'pnl_at_sl_excluding_commission': f"${get_pnl_at_price(sl_excluding_commission, last_tick_price, order_size_usd, LEVERAGE, order_type, commission)[1]:.5f}",
                        },
                    }
                    error_msg = f"Order failed to open for {pair}"
                    logger.error(error_msg, order, trade_info)
            else:
                message = f"No mean reversion detected for {pair}."
                logger.info(message)
        
    except requests.RequestException as e:
        error_msg = f"Error fetching MT5 data: {str(e)}"
        logger.error(error_msg)
    except Exception as e:
        error_msg = f"Exception in entry_algorithm: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)

