import time
import json
import logging
from .services.grid_bot import get_grid_parameters_data
from .services.quant import get_arbitrage_summary

logger = logging.getLogger(__name__)

def event_quants_master_data():
    while True:
        try:
            # todo: if every second get service is heavy load, considering change to use pusub strategy instead
            grid_data = get_grid_parameters_data()
            arbitrage_summary = get_arbitrage_summary()

            data = {
                'grid_data': grid_data,
                'arbitrage_summary': arbitrage_summary
            }

            # Format SSE protocol Data Response (data: <message>\n\n)
            yield f"data: {json.dumps(data)}\n\n"
        except Exception as e:
            logging.error(f"Stream quant master data error: {e}")
            break
        time.sleep(1)