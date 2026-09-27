from flask import Blueprint, jsonify
import MetaTrader5 as mt5
from flasgger import swag_from
import state

health_bp = Blueprint('health', __name__)

@health_bp.route('/health')
@swag_from({
    'tags': ['Health'],
    'responses': {
        200: {
            'description': 'MT5 connected and background poll is fresh',
            'schema': {'$ref': '#/definitions/HealthStatus'}
        },
        503: {
            'description': 'MT5 disconnected, or background poll older than the watchdog timeout',
            'schema': {'$ref': '#/definitions/HealthStatus'}
        }
    },
    'definitions': {
        'HealthStatus': {
            'type': 'object',
            'properties': {
                'status': {'type': 'string', 'enum': ['healthy', 'unhealthy']},
                'mt5_connected': {'type': 'boolean'},
                'mt5_initialized': {'type': 'boolean'},
                'poll_age_sec': {'type': 'number', 'description': 'Seconds since the last successful background poll'}
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
        description: MT5 connected and background poll is fresh
      503:
        description: MT5 disconnected or background poll is stale
    """
    initialized = mt5.terminal_info() is not None
    poll_age_sec = state.poll_age()
    healthy = initialized and poll_age_sec <= state.WATCHDOG_TIMEOUT
    return jsonify({
        "status": "healthy" if healthy else "unhealthy",
        "mt5_connected": initialized,
        "mt5_initialized": initialized,
        "poll_age_sec": round(poll_age_sec, 3)
    }), 200 if healthy else 503

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
                    'margin_mode': {'type': 'integer', 'description': 'ACCOUNT_MARGIN_MODE: 0 retail netting, 1 exchange, 2 retail hedging'},
                    'currency': {'type': 'string'},
                    'leverage': {'type': 'integer'},
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
            # margin_mode: ACCOUNT_MARGIN_MODE_RETAIL_NETTING=0, _EXCHANGE=1,
            # _RETAIL_HEDGING=2. Clients that hold opposing positions need 2.
            'margin_mode': account_info['margin_mode'],
            'currency': account_info['currency'],
            'leverage': account_info['leverage'],
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'error',
            'reason': str(e)
        }), 500
