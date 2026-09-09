from flask import Blueprint, jsonify
import MetaTrader5 as mt5
from flasgger import swag_from

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
    initialized = mt5.terminal_info() is not None
    return jsonify({
        "status": "healthy",
        "mt5_connected": initialized,
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
        account_info = mt5.account_info()
        if account_info is None:
            return jsonify({'status': 'error', 'reason': 'Failed to get account info'}), 500
        account_info = account_info._asdict()
        terminal_info = mt5.terminal_info()
        terminal_info = terminal_info._asdict() if terminal_info else {}
        return jsonify({
            'status': 'successful',
            'login': account_info['login'],
            'server': account_info['server'],
            'name': account_info['name'],
            # trade_allowed here is the account-level permission; terminal_info's
            # trade_allowed is the client terminal's AutoTrading button (retcode 10027).
            # trade_expert is the server-side EA/algo-trading permission — this is the
            # flag behind "AutoTrading disabled by server" (retcode 10026).
            'account_trade_allowed': account_info['trade_allowed'],
            'account_trade_expert': account_info['trade_expert'],
            'terminal_trade_allowed': terminal_info.get('trade_allowed'),
            'trade_mode': account_info['trade_mode'],
            'margin_level': account_info['margin_level'],
            'margin_so_call': account_info['margin_so_call'],
            'margin_so_so': account_info['margin_so_so'],
            'equity': account_info['equity'],
            'balance': account_info['balance'],
            'credit': account_info['credit'],
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'error',
            'reason': str(e)
        }), 500
