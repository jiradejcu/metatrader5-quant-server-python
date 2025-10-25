import logging
import asyncio
from django.core.management.base import BaseCommand
from app.connectors.binance.api.position import subscribe_position_information

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class Command(BaseCommand):
    def handle(self, *args, **options):
        logger.info(self.style.SUCCESS("Connecting to Binance WebSocket for position information..."))
        asyncio.run(subscribe_position_information("PAXGUSDT"))
