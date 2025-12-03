from django.shortcuts import render
import json
from app.utils.redis_client import get_redis_connection
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import logging


logger = logging.getLogger(__name__)
def prepare_json(json_str):
    if json_str == None:
            return {}
    return json.loads(json_str)

def health_check_page(request):
    # todo dynamic value
    binance_symbol = 'PAXGUSDT'
    mt5_symbol = 'XAUUSD'
    ratio = 1 # edit to 100 after changing contract_size in position_sync

    redis_conn = get_redis_connection()
    binance_key = f"position:{binance_symbol}"
    mt5_key = f"position: {mt5_symbol}"
    pause_position_key = f"position_sync_paused_flag"

    # Retrieve cache data
    data = redis_conn.get(binance_key)
    mt5_data = redis_conn.get(mt5_key)
    pause_position = 'Active'

    result = prepare_json(data)
    mt5_result = prepare_json(mt5_data)

    binance_action = 'SHORT'
    mt5_action  = 'SHORT'
    pairStatus = 'Warning'

    binance_size = float(result['positionAmt'])
    mt5_size = float(mt5_result['positionAmt'])
    unrealizes = [float(result['unRealizedProfit']), float(mt5_result['unRealizedProfit'])]

    # Condition defined
    if binance_size > 0:
        binance_action = 'LONG'
    if binance_size == 0:
        binance_action = 'None'
    if mt5_size > 0:
        mt5_action = 'LONG'
    if mt5_size == 0:
        mt5_action = 'None'
    if (binance_size + mt5_size) == 0:
        pairStatus = 'Complete'
    if redis_conn.get(pause_position_key):
        pause_position = 'Pause'


    context = {
        'binanceMarkPrice': result['markPrice'],
        'mt5MarkPrice': mt5_result['markPrice'],
        'spread': float(result['markPrice']) - float(mt5_result['markPrice']),
        'pairStatus': pairStatus,
        'binanceSize': binance_size,
        'binanceAction': binance_action,
        'mt5Size': mt5_size,
        'netExpose': (binance_size * ratio) + mt5_size,
        'mt5Action': mt5_action,
        'unrealizedBinance': sum(unrealizes),
        'pausePositionSync': pause_position,
        'time_update_mt5': mt5_result['time_update'],
    }
    return render(request, 'health-check.html', context)

@api_view(['POST'])
def handle_pause_position_sync():
    try:
        redis_conn = get_redis_connection()
        redis_key = f"position_sync_paused_flag"

        is_paused = redis_conn.exists(redis_key)

        # Have key exist => when request called it for starting bot position sync back
        if is_paused:
            redis_conn.delete(redis_key)
            message = "Sync is resumed. Bot position sync is now ACTIVE."
            return Response({"message": message, "is_paused": False}, status=status.HTTP_200_OK)
        
        # Haven't key exist -> when request called it for pausing bot position sync
        redis_conn.set(redis_key, 'PAUSED')
        message = "Sync is paused. Bot position sync is STOPPED."
        print(f"New TTL for 'temp_key': {redis_conn.ttl('temp_key')}")  # Output: -1
        return Response({"message": message, "is_paused": True}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Pausing bot error: {e}")
        return Response({"message": f"Server error: {e}", "is_paused": None}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


