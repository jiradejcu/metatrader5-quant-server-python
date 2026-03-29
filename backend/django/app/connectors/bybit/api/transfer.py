import os
import uuid
import logging
from dotenv import load_dotenv
from pybit.unified_trading import HTTP

load_dotenv()
logger = logging.getLogger(__name__)

session = HTTP(
    testnet=False,
    api_key=os.environ.get('API_KEY_BYBIT'),
    api_secret=os.environ.get('API_SECRET_BYBIT'),
)

ACCOUNT_UNIFIED = 'UNIFIED'
ACCOUNT_FUND = 'FUND'


def get_transferable_amount(coin: str, from_account: str):
    """Returns the available balance of a coin in the given account."""
    try:
        if from_account == ACCOUNT_UNIFIED:
            response = session.get_wallet_balance(accountType=ACCOUNT_UNIFIED)
            if response.get('retCode') != 0:
                logger.error(f"Get transferable amount error: {response.get('retMsg')}")
                return None
            coins = response.get('result', {}).get('list', [{}])[0].get('coin', [])
            match = next((c for c in coins if c.get('coin') == coin), None)
            return {'coin': coin, 'transferBalance': match.get('walletBalance', '0') if match else '0'}
        else:
            response = session.get_coins_balance(accountType=from_account, coin=coin)
            if response.get('retCode') != 0:
                logger.error(f"Get transferable amount error: {response.get('retMsg')}")
                return None
            coins = response.get('result', {}).get('balance', [])
            match = next((c for c in coins if c.get('coin') == coin), None)
            return {'coin': coin, 'transferBalance': match.get('walletBalance', '0') if match else '0'}
    except Exception as e:
        logger.error(f"Get transferable amount error: {e}")
        return None


def transfer(coin: str, amount: str, from_account: str, to_account: str):
    """
    Transfer between UNIFIED and FUND accounts.
    from_account / to_account: 'UNIFIED' or 'FUND'
    Returns the transfer ID on success, None on failure.
    """
    try:
        transfer_id = str(uuid.uuid4())
        response = session.create_internal_transfer(
            transferId=transfer_id,
            coin=coin,
            amount=str(amount),
            fromAccountType=from_account,
            toAccountType=to_account,
        )
        if response.get('retCode') != 0:
            logger.error(f"Transfer error: {response.get('retMsg')}")
            return None
        result = response.get('result', {})
        logger.info(f"Transfer successful: {from_account} -> {to_account} {amount} {coin}, transferId={result.get('transferId')}")
        return result.get('transferId')
    except Exception as e:
        logger.error(f"Transfer error: {e}")
        return None


def transfer_to_fund(coin: str, amount: str):
    return transfer(coin, amount, from_account=ACCOUNT_UNIFIED, to_account=ACCOUNT_FUND)


def transfer_to_unified(coin: str, amount: str):
    return transfer(coin, amount, from_account=ACCOUNT_FUND, to_account=ACCOUNT_UNIFIED)


def get_transfer_records(coin: str = None, limit: int = 20):
    try:
        params = {'limit': limit}
        if coin:
            params['coin'] = coin
        response = session.get_internal_transfer_records(**params)
        if response.get('retCode') != 0:
            logger.error(f"Get transfer records error: {response.get('retMsg')}")
            return []
        return response.get('result', {}).get('list', [])
    except Exception as e:
        logger.error(f"Get transfer records error: {e}")
        return []
