from django.shortcuts import render
import json
from app.utils.redis_client import get_redis_connection

def prepare_json(json_str):
    return json.loads(json_str)

def health_check_page(request):
    # todo dynamic value
    binance_symbol = 'PAXGUSDT'
    mt5_symbol = 'XAUUSD'
    ratio = 1 # edit to 100 after changing contract_size in position_sync

    redis_conn = get_redis_connection()
    binance_key = f"position:{binance_symbol}"
    mt5_key = f"position: {mt5_symbol}"

    # Retrieve cache data
    data = redis_conn.get(binance_key)
    mt5_data = redis_conn.get(mt5_key)

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
    if mt5_size > 0:
        mt5_action = 'LONG'
    if (binance_size + mt5_size) == 0:
        pairStatus = 'Complete'


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
        'unrealizedBinance': sum(unrealizes)
    }
    return render(request, 'health-check.html', context)