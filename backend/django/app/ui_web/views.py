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
    entry_symbol = 'PAXGUSDT'
    hedge_symbol = 'XAUUSD'
    ratio = 1 # edit to 100 after changing contract_size in position_sync

    redis_conn = get_redis_connection()
    entry_key = f"position:binance:{entry_symbol}"
    hedge_key = f"position:mt5:{hedge_symbol}"
    pause_position_key = f"position_sync_paused_flag"

    # Retrieve cache data
    data = redis_conn.get(entry_key)
    hedge_data = redis_conn.get(hedge_key)
    pause_position = 'Active'

    result = prepare_json(data)
    hedge_result = prepare_json(hedge_data)

    entry_action = 'SHORT'
    hedge_action  = 'SHORT'
    pairStatus = 'Warning'

    entry_size = float(result['positionAmt'])
    hedge_size = float(hedge_result['positionAmt'])
    unrealizes = [float(result['unRealizedProfit']), float(hedge_result['unRealizedProfit'])]
    netExpose = (entry_size * ratio) + hedge_size
    netExposeAction = 'Safe'

    if netExpose != 0:
        netExposeAction = 'Unsafe'

    # Condition defined
    if entry_size > 0:
        entry_action = 'LONG'
    if entry_size == 0:
        entry_action = 'None'
    if hedge_size > 0:
        hedge_action = 'LONG'
    if hedge_size == 0:
        hedge_action = 'None'
    if (entry_size + hedge_size) == 0:
        pairStatus = 'Complete'
    if redis_conn.get(pause_position_key):
        pause_position = 'Pause'


    context = {
        'entryMarkPrice': result['markPrice'],
        'hedgeMarkPrice': hedge_result['markPrice'],
        'spread': float(result['markPrice']) - float(hedge_result['markPrice']),
        'pairStatus': pairStatus,
        'entrySize': entry_size,
        'entryAction': entry_action,
        'hedgeSize': hedge_size,
        'netExpose': netExpose,
        'netExposeAction': netExposeAction,
        'hedgeAction': hedge_action,
        'unrealizedTotal': sum(unrealizes),
        'pausePositionSync': pause_position,
        'time_update_hedge': hedge_result['time_update'],
        'time_update_entry': result['updateTime']
    }
    return render(request, 'health-check.html', context)

@api_view(['GET'])
def get_arbitrage_summary(request):
    try:
        entry_symbol = 'PAXGUSDT'
        hedge_symbol = 'XAUUSD'
        ratio = 1 # edit to 100 after changing contract_size in position_sync

        redis_conn = get_redis_connection()
        entry_key = f"position:binance:{entry_symbol}"
        hedge_key = f"position:mt5:{hedge_symbol}"
        pause_position_key = f"position_sync_paused_flag"

        # Retrieve cache data
        data = redis_conn.get(entry_key)
        hedge_data = redis_conn.get(hedge_key)
        pause_position = 'Active'

        result = prepare_json(data)
        hedge_result = prepare_json(hedge_data)

        entry_action = 'SHORT'
        hedge_action  = 'SHORT'
        pairStatus = 'Warning'

        entry_size = float(result['positionAmt'])
        hedge_size = float(hedge_result['positionAmt'])
        unrealizes = [float(result['unRealizedProfit']), float(hedge_result['unRealizedProfit'])]
        netExpose = (entry_size * ratio) + hedge_size
        netExposeAction = 'Safe'

        if netExpose != 0:
            netExposeAction = 'Unsafe'

        # Condition defined
        if entry_size > 0:
            entry_action = 'LONG'
        if entry_size == 0:
            entry_action = 'None'
        if hedge_size > 0:
            hedge_action = 'LONG'
        if hedge_size == 0:
            hedge_action = 'None'
        if (entry_size + hedge_size) == 0:
            pairStatus = 'Complete'
        if redis_conn.get(pause_position_key):
            pause_position = 'Pause'


        data = {
            'entryMarkPrice': result['markPrice'],
            'hedgeMarkPrice': hedge_result['markPrice'],
            'spread': float(result['markPrice']) - float(hedge_result['markPrice']),
            'pairStatus': pairStatus,
            'entrySize': entry_size,
            'entryAction': entry_action,
            'hedgeSize': hedge_size,
            'netExpose': netExpose,
            'netExposeAction': netExposeAction,
            'hedgeAction': hedge_action,
            'unrealizedTotal': sum(unrealizes),
            'pausePositionSync': pause_position,
            'time_update_hedge': hedge_result['time_update'],
            'time_update_entry': result['updateTime']
        }

        return Response({ message: "Successful retrieved summary data", data: data }, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Pausing bot error: {e}")
        return Response({"message": f"Server error: {e}", "is_paused": None}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
def handle_pause_position_sync(request):
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


