import logging
import asyncio
from django.core.management.base import BaseCommand
from app.connectors.bybit.api.position import subscribe_position_information

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    def handle(self, *args, **options):
        logger.info(self.style.SUCCESS("Connecting to Bybit for position information..."))
        asyncio.run(subscribe_position_information("BTCUSDT"))
