import logging
from django.core.management.base import BaseCommand
from app.connectors.hyperliquid.api.ticker import subscribe_symbol_ticker

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    def handle(self, *args, **options):
        logger.info(self.style.SUCCESS("Connecting to Hyperliquid WebSocket for bbo ticker stream..."))
        subscribe_symbol_ticker("BTC")
