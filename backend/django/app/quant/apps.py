from django.apps import AppConfig

class QuantConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app.quant'

    def ready(self):
        from .algorithms.arbitrage import subscribe
        subscribe.start_subscriptions()
        
        from .algorithms.arbitrage import position_sync
        position_sync.start_position_sync()

        # Add new worker to work as the bot grid (buying order when trigger upper and lower conditions)
        
        from .algorithms.arbitrage import price_diff
        price_diff.start_comparison()

        # Send notification to telegram group when price diff cross the grid channel
        from .algorithms.arbitrage import grid_bot
        grid_bot.start_grid_bot_sync()