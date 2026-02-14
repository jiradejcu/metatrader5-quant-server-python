from flask import Blueprint, jsonify, request, Response, stream_with_context
from utils.redis_client import get_redis_connection
import logging
import docker
import json
import requests
import os
from dotenv import load_dotenv
from constants.config import PAIRS
from events.master import event_quants_master_data

load_dotenv()
MT5_URL = os.getenv('API_DOMAIN')
BINANCE_KEY = os.getenv('API_KEY_BINANCE')
HOLDER_NAME = os.getenv('HOLDER_NAME')
PAIR_INDEX = int(os.getenv('PAIR_INDEX'))
RATIO_EXPOSE= int(os.getenv('CONTRACT_SIZE'))

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
        return jsonify({'status': 'ignored', 'message': 'Container does not exist'}), 404
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
        binance_symbol = PAIRS[PAIR_INDEX]['binance']
        mt5_symbol = PAIRS[PAIR_INDEX]['mt5']
        ratio = RATIO_EXPOSE

        binance_key = f"position:{binance_symbol}"
        mt5_key = f"position: {mt5_symbol}"
        pause_position_key = "position_sync_paused_flag"

        redis_conn = get_redis_connection()

        result = prepare_json(redis_conn.get(binance_key))
        logger.info(f"Get redis key: position: {binance_symbol} success")
        mt5_result = prepare_json(redis_conn.get(mt5_key))
        logger.info(f"Get redis key: position: {mt5_symbol} success")
        pause_position = 'Active'

        binance_action = 'SHORT'
        mt5_action = 'SHORT'
        pairStatus = 'Warning'

        binance_size = float(result.get('positionAmt', 0))
        mt5_size = float(mt5_result.get('positionAmt', 0))
        unrealizes = [float(result.get('unRealizedProfit', 0)), float(mt5_result.get('unRealizedProfit', 0))]
        netExpose = binance_size + (mt5_size * ratio) # 1 PAXG = 0.01 XAU
        netExposeAction = 'Safe'

        # handle floating point issue
        epsilon = 1e-12 
        if abs(netExpose) < epsilon:
            netExpose = 0

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

        if netExpose == 0:
            pairStatus = 'Complete'

        if redis_conn.get(pause_position_key):
            pause_position = 'Pause' 

        response_data = {
            'binanceMarkPrice': result.get('markPrice'),
            'mt5MarkPrice': mt5_result.get('markPrice'),
            'binanceEntry': result.get('entryPrice'),
            'mt5Entry': mt5_result.get('entryPrice'),
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
            'time_update_binance': result.get('updateTime'),
            'binanceSymbol': binance_symbol,
            'mt5Symbol': mt5_symbol,
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

@control_bp.route('/pause-grid-bot', methods=['POST'])
def handle_pause_grid_bot():
    try:
        redis_key = "grid_bot_paused_flag"
        redis_conn = get_redis_connection()
        is_paused = redis_conn.exists(redis_key)

        if is_paused:
            redis_conn.delete(redis_key)
            return jsonify({
                "message": "Sync is resumed. Grid bot is now ACTIVE.",
                "is_paused": False
            }), 200
        
        redis_conn.set(redis_key, 'PAUSED')
        logger.info("Successful handle pause grid bot!!")
        return jsonify({
            "message": "Sync is paused. Grid bot is STOPPED.",
            "is_paused": True
        }), 200

    except Exception as e:
        logger.error(f"Pausing grid bot error: {e}")
        return jsonify({"message": f"Server error: {str(e)}", "is_paused": None}), 500

@control_bp.route('/user-info', methods=['GET'])
def get_active_user_info():
    try:
        api_url = 'https://' + MT5_URL + '/account_info'
        response = requests.get(api_url)
        data = response.json()
        print(data)

        return jsonify({
            'status': 'successful',
            'login': data['login'],
            'server': data['server'],
            'name': data['name'],
            'binance_key': BINANCE_KEY,
            'binance_account_name': HOLDER_NAME
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'error',
            'reason': str(e)
        }), 500

@control_bp.route('/restart', methods=['POST'])
def restart_container():
    try:
        data = request.get_json()
        
        if not data or 'container' not in data:
            return jsonify({
                'status': 'error',
                'message': 'Missing "container" in request body'
            }), 400
        container_name = data['container']
        client = docker.from_env()
        

        container = client.containers.get(container_name)

        container.restart()

        return jsonify({
            'status': 'successful',
            'message': f"Container {container_name} has been restarted!"
        }), 200
    except docker.errors.NotFound:
        return jsonify({'status': 'ignored', 'message': 'Container does not exist'}), 404
    except Exception as e:
        return jsonify({
            'status': 'error',
            'reason': str(e)
        }), 500

@control_bp.route('/set-grid-channel', methods=['POST'])
def set_grid_setting_values():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'Required define data on body!!'}), 400
        
        # 1. Validate required fields and types
        required_fields = [
            'upper_diff', 'lower_diff', 'max_position_size', 
            'order_size', 'close_long', 'close_short'
        ]
        
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'status': 'error', 
                    'message': f'Required attribute "{field}" is missing!'
                }), 400
            if not isinstance(data[field], (int, float)):
                return jsonify({
                    'status': 'error', 
                    'message': f'Attribute "{field}" must be numeric!'
                }), 400

        upper = float(data['upper_diff'])
        lower = float(data['lower_diff'])
        max_pos = float(data['max_position_size'])
        ord_size = float(data['order_size'])
        c_long = float(data['close_long'])
        c_short = float(data['close_short'])

        # Validation Logic
        errors = []
        if not (ord_size < max_pos):
            errors.append("order_size must be less than max_position_size")
        if not (upper >= c_long):
            errors.append("upper_diff must be greater than or equal to close_long")
        if not (upper >= c_short):
            errors.append("upper_diff must be greater than or equal to close_short")
        if not (c_short >= lower):
            errors.append("close_short must be greater than or equal to lower_diff")
        if not (c_long >= lower):
            errors.append("close_long must be greater than or equal to lower_diff")
        if not (upper > lower):
            errors.append("upper_diff must be greater than lower_diff")

        if errors:
            return jsonify({
                'status': 'error',
                'message': 'Validation failed',
                'errors': errors
            }), 400

        # Process Redis Update
        PAIR_INDEX = int(os.getenv('PAIR_INDEX', 0))
        binance_symbol = PAIRS[PAIR_INDEX]['binance']
        mt5_symbol = PAIRS[PAIR_INDEX]['mt5']
        
        redis_conn = get_redis_connection()
        redis_key = f"setting_grid_channel:{binance_symbol}:{mt5_symbol}"

        grid_channel = {
            "upper_diff": upper,
            "lower_diff": lower,
            "max_position_size": max_pos,
            "order_size": ord_size,
            "close_long": c_long,
            "close_short": c_short
        }
        
        payload = json.dumps(grid_channel)
        
        redis_conn.set(redis_key, payload)
        redis_conn.publish(redis_key, payload)

        return jsonify({
            'status': 'successful',
            'message': "Grid channel settings updated successfully",
            'data': grid_channel
        }), 200

    except Exception as e:
        return jsonify({
            'status': 'error',
            'reason': str(e)
        }), 500


@control_bp.route('/stream/quants', methods=['GET'])
def stream_quant_master_data():
    return Response(stream_with_context(event_quants_master_data()), mimetype="text/event-stream")