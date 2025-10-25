import logging
import asyncio
from django.core.management.base import BaseCommand
from app.connectors.binance.api.ticker import subscribe_symbol_ticker

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    def handle(self, *args, **options):
        logger.info(self.style.SUCCESS("Connecting to Binance WebSocket for individual symbol ticker streams..."))
        asyncio.run(subscribe_symbol_ticker("PAXGUSDT"))
