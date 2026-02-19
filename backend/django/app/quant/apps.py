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