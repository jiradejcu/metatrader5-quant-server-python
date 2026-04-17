import logging
from django.core.management.base import BaseCommand
from app.connectors.bybit.api.ticker import subscribe_symbol_ticker

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    def handle(self, *args, **options):
        logger.info(self.style.SUCCESS("Connecting to Bybit WebSocket for individual symbol ticker streams..."))
        subscribe_symbol_ticker("BTCUSDT")
