from flask import Blueprint, jsonify, request
import MetaTrader5 as mt5
import logging
from flasgger import swag_from

withdraw_bp = Blueprint('withdraw', __name__)
logger = logging.getLogger(__name__)


@withdraw_bp.route('/account_balance', methods=['GET'])
@swag_from({
    'tags': ['Withdraw'],
    'responses': {
        200: {
            'description': 'Account balance retrieved successfully.',
            'schema': {
                'type': 'object',
                'properties': {
                    'status': {'type': 'string'},
                    'balance': {'type': 'number'},
                    'equity': {'type': 'number'},
                    'profit': {'type': 'number'},
                    'credit': {'type': 'number'},
                    'margin': {'type': 'number'},
                    'margin_free': {'type': 'number'},
                    'margin_level': {'type': 'number'},
                    'currency': {'type': 'string'},
                }
            }
        },
        500: {'description': 'Internal server error.'}
    }
})
def get_account_balance():
    """
    Get Account Balance
    ---
    description: Retrieve the full financial details of the MT5 trading account.
    """
    try:
        if not mt5.initialize():
            return jsonify({'status': 'error', 'reason': 'Failed to initialize MT5'}), 500

        info = mt5.account_info()
        if info is None:
            return jsonify({'status': 'error', 'reason': 'Failed to retrieve account info'}), 500

        info_dict = info._asdict()
        return jsonify({
            'status': 'successful',
            'balance': info_dict['balance'],
            'equity': info_dict['equity'],
            'profit': info_dict['profit'],
            'credit': info_dict['credit'],
            'margin': info_dict['margin'],
            'margin_free': info_dict['margin_free'],
            'margin_level': info_dict['margin_level'],
            'currency': info_dict['currency'],
        }), 200
    except Exception as e:
        logger.error(f"Error in get_account_balance: {str(e)}")
        return jsonify({'status': 'error', 'reason': str(e)}), 500


@withdraw_bp.route('/withdraw', methods=['POST'])
@swag_from({
    'tags': ['Withdraw'],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'amount': {'type': 'number', 'description': 'Amount to withdraw'},
                    'comment': {'type': 'string', 'description': 'Withdrawal comment/reference'},
                },
                'required': ['amount']
            }
        }
    ],
    'responses': {
        200: {
            'description': 'Withdrawal request sent successfully.',
            'schema': {
                'type': 'object',
                'properties': {
                    'status': {'type': 'string'},
                    'retcode': {'type': 'integer'},
                    'comment': {'type': 'string'},
                    'result': {'type': 'object'},
                }
            }
        },
        400: {'description': 'Bad request or withdrawal failed.'},
        500: {'description': 'Internal server error.'}
    }
})
def withdraw():
    """
    Withdraw Funds
    ---
    description: Submit a withdrawal request from the MT5 trading account.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        amount = data.get('amount')
        if amount is None:
            return jsonify({'error': 'amount is required'}), 400

        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return jsonify({'error': 'amount must be a number'}), 400

        if amount <= 0:
            return jsonify({'error': 'amount must be greater than zero'}), 400

        if not mt5.initialize():
            return jsonify({'error': 'Failed to initialize MT5'}), 500

        info = mt5.account_info()
        if info is None:
            return jsonify({'error': 'Failed to retrieve account info'}), 500

        if amount > info.balance:
            return jsonify({
                'error': 'Insufficient balance',
                'balance': info.balance,
                'requested': amount,
            }), 400

        request_data = {
            'action': mt5.TRADE_ACTION_WITHDRAW_CREDIT,
            'amount': amount,
            'comment': data.get('comment', ''),
        }

        logger.info(f"Withdrawal request: amount={amount}, comment={data.get('comment', '')}")
        result = mt5.order_send(request_data)

        if result is None:
            error_code, error_str = mt5.last_error()
            logger.error(f"Withdrawal failed: {error_str}")
            return jsonify({
                'error': 'Withdrawal request failed',
                'mt5_error': error_str,
            }), 400

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Withdrawal failed with retcode {result.retcode}: {result.comment}")
            return jsonify({
                'error': f'Withdrawal failed: {result.comment}',
                'retcode': result.retcode,
                'result': result._asdict(),
            }), 400

        logger.info(f"Withdrawal successful: retcode={result.retcode}")
        return jsonify({
            'status': 'successful',
            'retcode': result.retcode,
            'comment': result.comment,
            'result': result._asdict(),
        }), 200

    except Exception as e:
        logger.error(f"Error in withdraw: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
