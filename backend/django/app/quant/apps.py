import os
import threading
from django.apps import AppConfig

class QuantConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app.quant'

    def ready(self):
        from .algorithms.arbitrage import subscribe
        subscribe.start_subscriptions()
        
        from .algorithms.arbitrage import position_sync
        position_sync.start_position_sync()

        from .algorithms.arbitrage import net_position
        net_position.start_net_position_check()
        
        from .algorithms.arbitrage import price_diff
        price_diff.start_comparison()

        from .algorithms.arbitrage import grid_bot
        grid_bot.start_grid_bot_sync()

        from .algorithms.arbitrage import health_monitor
        health_monitor.start_health_monitor()

        if os.environ.get('RUN_MAIN') != 'true':
            return

        from app.quant.algorithms.arbitrage import config
        pair_index_env = os.getenv('PAIR_INDEX')
        if pair_index_env is not None:
            pair = config.PAIRS[int(pair_index_env)]
            entry_exchange = pair['entry']['exchange']
            entry_symbol = pair['entry']['symbol']
            hedge_exchange = pair['hedge']['exchange']
            hedge_symbol = pair['hedge']['symbol']

            if entry_exchange == 'binance':
                from app.connectors.binance.api.ticker import fetch_ticker_data as fetch_binance_ticker_data
                fetch_binance_ticker_data(entry_symbol)
            elif entry_exchange == 'bybit':
                from app.connectors.bybit.api.ticker import fetch_ticker_data as fetch_bybit_ticker_data
                fetch_bybit_ticker_data(entry_symbol)

            if hedge_exchange == 'mt5':
                from app.utils.api.data import subscribe_symbol_ticker as subscribe_mt5_ticker
                threading.Thread(target=subscribe_mt5_ticker, args=(hedge_symbol,), daemon=True).start()