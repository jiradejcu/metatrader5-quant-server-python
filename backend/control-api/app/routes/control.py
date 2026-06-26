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
from events.services.quant import get_arbitrage_summary as _get_arbitrage_summary

load_dotenv()
MT5_URL = os.getenv('API_DOMAIN')
BINANCE_KEY = os.getenv('API_KEY_BINANCE')
HOLDER_NAME = os.getenv('HOLDER_NAME')
PAIR_INDEX = int(os.getenv('PAIR_INDEX'))

logger = logging.getLogger(__name__)
control_bp = Blueprint('control', __name__)
TARGET_CONTAINER = "django"


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
        logger.error(f"Stop quant container error: {e}")
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
        logger.error(f"Get django status error: {e}")
        return jsonify({
            'status': 'error',
            'reason': str(e)
        }), 500

@control_bp.route('/get-arbitrage-summary', methods=['GET'])
def get_arbitrage_summary():
    try:
        data = _get_arbitrage_summary()
        return jsonify({"message": "Successful retrieved summary data", "data": data}), 200
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
        # logger.info("Successful handle pause position sync!!")
        return jsonify({
            "message": "Sync is paused. Bot position sync is STOPPED.",
            "is_paused": True
        }), 200

    except Exception as e:
        logger.error(f"Pausing bot error: {e}")
        return jsonify({"message": f"Server error: {str(e)}", "is_paused": None}), 500

@control_bp.route('/toggle-grid-bot', methods=['POST'])
def handle_toggle_grid_bot():
    try:
        redis_key = "grid_bot_active_flag"
        redis_conn = get_redis_connection()
        is_active = redis_conn.exists(redis_key)

        if is_active:
            redis_conn.delete(redis_key)
            return jsonify({
                "message": "Grid bot is now INACTIVE.",
                "is_active": False
            }), 200

        redis_conn.set(redis_key, 'ACTIVE')
        return jsonify({
            "message": "Grid bot is now ACTIVE.",
            "is_active": True
        }), 200

    except Exception as e:
        logger.error(f"Pausing grid bot error: {e}")
        return jsonify({"message": f"Server error: {str(e)}", "is_active": None}), 500

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
        logger.error(f"Get user info error: {e}")
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
        logger.error(f"Restart container error: {e}")
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

        logger.info(f"Grid setting update requested: {data}")

        # 1. Validate required fields and types
        required_fields = [
            'long_upper_limit', 'long_lower_limit',
            'short_upper_limit', 'short_lower_limit',
            'max_position_size', 'order_size',
        ]

        for field in required_fields:
            if field not in data:
                logger.warning(f"Grid setting update rejected — missing field: {field}")
                return jsonify({
                    'status': 'error',
                    'message': f'Required attribute "{field}" is missing!'
                }), 400
            if not isinstance(data[field], (int, float)):
                logger.warning(f"Grid setting update rejected — non-numeric field: {field}={data[field]!r}")
                return jsonify({
                    'status': 'error',
                    'message': f'Attribute "{field}" must be numeric!'
                }), 400

        long_upper = float(data['long_upper_limit'])
        long_lower = float(data['long_lower_limit'])
        short_upper = float(data['short_upper_limit'])
        short_lower = float(data['short_lower_limit'])
        max_pos = float(data['max_position_size'])
        ord_size = float(data['order_size'])
        # Validation Logic
        errors = []
        if ord_size <= 0:
            errors.append("order_size must be greater than 0")
        if max_pos < 0:
            errors.append("max_position_size must be greater than 0")

        if not (long_upper > long_lower):
            errors.append("long_upper_limit must be greater than long_lower_limit")
        if not (short_upper > short_lower):
            errors.append("short_upper_limit must be greater than short_lower_limit")

        if errors:
            logger.warning(f"Grid setting update rejected — validation errors: {errors}")
            return jsonify({
                'status': 'error',
                'message': 'Validation failed',
                'errors': errors
            }), 400

        # Process Redis Update
        PAIR_INDEX = int(os.getenv('PAIR_INDEX', 0))
        primary_symbol = PAIRS[PAIR_INDEX]['primary']['symbol']
        hedge_symbol = PAIRS[PAIR_INDEX]['hedge']['symbol']

        redis_conn = get_redis_connection()
        redis_key = f"setting_grid_channel:{primary_symbol}:{hedge_symbol}"

        grid_channel = {
            "long_upper_limit": long_upper,
            "long_lower_limit": long_lower,
            "short_upper_limit": short_upper,
            "short_lower_limit": short_lower,
            "max_position_size": max_pos,
            "order_size": ord_size,
        }

        payload = json.dumps(grid_channel)

        redis_conn.set(redis_key, payload)
        redis_conn.publish(redis_key, payload)

        logger.info(f"Grid setting updated successfully [{primary_symbol}/{hedge_symbol}]: {grid_channel}")

        return jsonify({
            'status': 'successful',
            'message': "Grid channel settings updated successfully",
            'data': grid_channel
        }), 200

    except Exception as e:
        logger.error(f"Set grid channel error: {e}")
        return jsonify({
            'status': 'error',
            'reason': str(e)
        }), 500


_DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

def _trading_sessions_key():
    primary_symbol = PAIRS[PAIR_INDEX]['primary']['symbol']
    hedge_symbol = PAIRS[PAIR_INDEX]['hedge']['symbol']
    return f"trading_sessions:{primary_symbol}:{hedge_symbol}"


@control_bp.route('/trading-sessions', methods=['GET'])
def get_trading_sessions():
    try:
        redis_conn = get_redis_connection()
        raw = redis_conn.get(_trading_sessions_key())
        if not raw:
            default = {day: [] for day in _DAYS}
            return jsonify({'status': 'successful', 'data': default}), 200
        return jsonify({'status': 'successful', 'data': json.loads(raw)}), 200
    except Exception as e:
        logger.error(f"Get trading sessions error: {e}")
        return jsonify({'status': 'error', 'reason': str(e)}), 500


@control_bp.route('/trading-sessions', methods=['POST'])
def set_trading_sessions():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'Request body required'}), 400

        # Validate structure
        for day in _DAYS:
            if day not in data:
                return jsonify({'status': 'error', 'message': f'Missing day: {day}'}), 400
            for r in data[day]:
                if 'start' not in r or 'end' not in r:
                    return jsonify({'status': 'error', 'message': f'Each range must have start and end for {day}'}), 400
                for field in ('start', 'end'):
                    parts = r[field].split(':')
                    if len(parts) != 2 or not all(p.isdigit() for p in parts):
                        return jsonify({'status': 'error', 'message': f'Invalid time format "{r[field]}" for {day}'}), 400
                    h, m = int(parts[0]), int(parts[1])
                    if not (0 <= h <= 24 and 0 <= m <= 59):
                        return jsonify({'status': 'error', 'message': f'Invalid time value "{r[field]}" for {day}'}), 400

        ordered = {
            day: [{'start': r['start'], 'end': r['end']} for r in data[day]]
            for day in _DAYS
        }

        redis_conn = get_redis_connection()
        redis_conn.set(_trading_sessions_key(), json.dumps(ordered))

        logger.info(f"Trading sessions updated: {ordered}")
        return jsonify({'status': 'successful', 'data': ordered}), 200
    except Exception as e:
        logger.error(f"Set trading sessions error: {e}")
        return jsonify({'status': 'error', 'reason': str(e)}), 500


@control_bp.route('/stream/quants', methods=['GET'])
def stream_quant_master_data():
    return Response(stream_with_context(event_quants_master_data()), mimetype="text/event-stream")