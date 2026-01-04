from flask import Blueprint, jsonify
import MetaTrader5 as mt5
from flasgger import swag_from
import os
from dotenv import load_dotenv

load_dotenv()
BINANCE_KEY = os.getenv('API_KEY_BINANCE')

health_bp = Blueprint('health', __name__)

@health_bp.route('/health')
@swag_from({
    'tags': ['Health'],
    'responses': {
        200: {
            'description': 'Health check successful',
            'schema': {
                'type': 'object',
                'properties': {
                    'status': {'type': 'string'},
                    'mt5_connected': {'type': 'boolean'},
                    'mt5_initialized': {'type': 'boolean'}
                }
            }
        }
    }
})
def health_check():
    """
    Health Check Endpoint
    ---
    description: Check the health status of the application and MT5 connection.
    responses:
      200:
        description: Health check successful
    """
    initialized = mt5.initialize() if mt5 is not None else False
    return jsonify({
        "status": "healthy",
        "mt5_connected": mt5 is not None,
        "mt5_initialized": initialized
    }), 200

@health_bp.route('/account_info')
@swag_from({
    'tags': ['Health'],
    'responses': {
        200: {
            'description': 'Get account information successful',
            'schema': {
                'type': 'object',
                'properties': {
                    'login': {'type': 'string'},
                    'name': {'type': 'string'},
                    'server': {'type': 'string'},
                    'status': {'type': 'string'},
                }
            }
        }
    }
})
def get_account_info():
    try:
        if not mt5.initialize():
            print("initialize() failed, error code =",mt5.last_error())
        account_info = mt5.account_info()._asdict()

        return jsonify({
            'status': 'successful',
            'login': account_info['login'],
            'server': account_info['server'],
            'name': account_info['name'],
            'binance_key': BINANCE_KEY
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'error',
            'reason': str(e)
        }), 500
