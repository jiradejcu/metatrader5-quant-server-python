from django.apps import AppConfig

class QuantConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app.quant'

    def ready(self):
        from .algorithms.arbitrage import subscribe
        subscribe.start_subscriptions()
        
        from .algorithms.arbitrage import position_sync
        position_sync.start_position_sync()