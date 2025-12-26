from flask import Blueprint, jsonify, request
from utils.redis_client import get_redis_connection
import logging
import docker
import json

logger = logging.getLogger(__name__)
control_bp = Blueprint('control', __name__)
TARGET_CONTAINER = "django"

def prepare_json(json_str):
    if json_str == None:
            return {'positionAmt': 0, 'markPrice': 0, 'unRealizedProfit': 0, 'time_update': None, 'updateTime': None}
    return json.loads(json_str)

@control_bp.route('/stop-quant', methods=['POST'])
def stop_quant_container():
    try:
        client = docker.from_env()
        client.ping()
        container = client.containers.get(TARGET_CONTAINER)
        
        # Check status directly from the object attribute
        if container.status == 'running':
            container.stop()
            return jsonify({
                'status': 'success',
                'message': f'Container {TARGET_CONTAINER} stopped'
            }), 200
        
        return jsonify({
            'status': 'ignored',
            'message': f'Container {TARGET_CONTAINER} was not running (Current status: {container.status})'
        }), 200
        
    except docker.errors.NotFound:
        return jsonify({'status': 'ignored', 'message': 'Container does not exist'}), 200
    except Exception as e:
        return jsonify({
            'status': 'error',
            'reason': str(e)
        }), 500

@control_bp.route('/get-django-status', methods=['GET'])
def get_django_status():
    try:
        client = docker.from_env()
        container = client.containers.get(TARGET_CONTAINER)

        current_status = container.status

        return jsonify({
            'container': TARGET_CONTAINER,
            'status': current_status,
            'is_running': current_status == 'running'
        }) , 200
    except docker.errors.NotFound:
        return jsonify({
            'status': 'error',
            'message': f'Container "{TARGET_CONTAINER} not found'
        }), 404
    except Exception as e:
        return jsonify({
            'status': 'error',
            'reason': str(e)
        }), 500

@control_bp.route('/get-arbitrage-summary', methods=['GET'])
def get_arbitrage_summary():
    try:
        binance_symbol = 'PAXGUSDT'
        mt5_symbol = 'XAUUSD'
        ratio = 1

        binance_key = f"position:{binance_symbol}"
        mt5_key = f"position: {mt5_symbol}"
        pause_position_key = "position_sync_paused_flag"

        redis_conn = get_redis_connection()

        result = prepare_json(redis_conn.get(binance_key))
        logger.info(f"Get redis key: position: {mt5_symbol} success")
        mt5_result = prepare_json(redis_conn.get(mt5_key))
        logger.info(f"Get redis key: position: {mt5_symbol} success")
        pause_position = 'Active'

        binance_action = 'SHORT'
        mt5_action = 'SHORT'
        pairStatus = 'Warning'

        binance_size = float(result.get('positionAmt', 0))
        mt5_size = float(mt5_result.get('positionAmt', 0))
        unrealizes = [float(result.get('unRealizedProfit', 0)), float(mt5_result.get('unRealizedProfit', 0))]
        netExpose = (binance_size * ratio) + mt5_size
        netExposeAction = 'Safe'

        if netExpose != 0:
            netExposeAction = 'Unsafe'

        if binance_size > 0:
            binance_action = 'LONG'
        elif binance_size == 0:
            binance_action = 'None'

        if mt5_size > 0:
            mt5_action = 'LONG'
        elif mt5_size == 0:
            mt5_action = 'None'

        if (binance_size + mt5_size) == 0:
            pairStatus = 'Complete'

        if redis_conn.get(pause_position_key):
            pause_position = 'Pause'

        response_data = {
            'binanceMarkPrice': result.get('markPrice'),
            'mt5MarkPrice': mt5_result.get('markPrice'),
            'spread': float(result.get('markPrice', 0)) - float(mt5_result.get('markPrice', 0)),
            'pairStatus': pairStatus,
            'binanceSize': binance_size,
            'binanceAction': binance_action,
            'mt5Size': mt5_size,
            'netExpose': netExpose,
            'netExposeAction': netExposeAction,
            'mt5Action': mt5_action,
            'unrealizedBinance': sum(unrealizes),
            'pausePositionSync': pause_position,
            'time_update_mt5': mt5_result.get('time_update'),
            'time_update_binance': result.get('updateTime')
        }

        logger.info("Successful get arbitrage information!!")
        return jsonify({"message": "Successful retrieved summary data", "data": response_data}), 200

    except Exception as e:
        logger.error(f"Summary data error: {e}")
        return jsonify({"message": f"Server error: {str(e)}", "data": None}), 500

@control_bp.route('/pause-position-sync', methods=['POST'])
def handle_pause_position_sync():
    try:
        redis_key = "position_sync_paused_flag"
        redis_conn = get_redis_connection()
        is_paused = redis_conn.exists(redis_key)

        if is_paused:
            redis_conn.delete(redis_key)
            return jsonify({
                "message": "Sync is resumed. Bot position sync is now ACTIVE.",
                "is_paused": False
            }), 200
        
        redis_conn.set(redis_key, 'PAUSED')
        logger.info("Successful handle pause position sync!!")
        return jsonify({
            "message": "Sync is paused. Bot position sync is STOPPED.",
            "is_paused": True
        }), 200

    except Exception as e:
        logger.error(f"Pausing bot error: {e}")
        return jsonify({"message": f"Server error: {str(e)}", "is_paused": None}), 500