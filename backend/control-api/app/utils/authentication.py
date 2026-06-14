from functools import wraps
from flask import request, jsonify

from utils.db import get_db_connection


def _get_user_for_token(token):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id, u.username, u.is_active, u.is_staff, u.is_superuser
                FROM authtoken_token t
                JOIN auth_user u ON u.id = t.user_id
                WHERE t.key = %s
                """,
                (token,),
            )
            return cur.fetchone()
    finally:
        conn.close()


def token_required(staff_only=False):
    """
    Decorator to protect control-api routes using Django's DRF auth token.
    Expects an 'Authorization: Token <key>' header, validated against the
    shared Django auth_user / authtoken_token tables.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('Token '):
                return jsonify({"message": "Authorization header must be 'Token <key>'"}), 401

            token = auth_header.split(' ', 1)[1].strip()
            if not token:
                return jsonify({"message": "Token is missing"}), 401

            row = _get_user_for_token(token)
            if not row:
                return jsonify({"message": "Invalid token"}), 401

            _, _, is_active, is_staff, is_superuser = row
            if not is_active:
                return jsonify({"message": "User account is inactive"}), 401

            if staff_only and not (is_staff or is_superuser):
                return jsonify({"message": "Admin privileges required"}), 403

            return f(*args, **kwargs)
        return decorated
    return decorator
