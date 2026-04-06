import jwt
from functools import wraps
from flask import jsonify, request
from models.user import User
import os
from dotenv import load_dotenv
from utils.redis_client import get_redis_connection

load_dotenv()

# Configuration
SECRET_KEY = os.getenv('SECRET_KEY', 'jwt-secret-key') 
ALGORITHM = "HS256"

def token_required(pass_user=False):
    """
    Decorator to protect routes. 
    Expects a 'Authorization: Bearer <token>' header.
    
    Args:
        pass_user (bool): If True, passes current_user to the function.
                         If False (default), does NOT pass current_user.
    
    Usage:
        @token_required()  # Does NOT pass current_user
        @token_required(pass_user=True)  # Passes current_user
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            token = None
            if 'Authorization' in request.headers:
                auth_header = request.headers['Authorization']
                try:
                    # Handle 'Bearer <token>'
                    token = auth_header.split(" ")[1]
                except IndexError:
                    return jsonify({"message": "Token format is 'Bearer <token>'"}), 401

            if not token:
                return jsonify({"message": "Token is missing"}), 401

            try:
                # Check if token is blacklisted
                redis_conn = get_redis_connection()
                if redis_conn.exists(f"blacklist:{token}"):
                    return jsonify({"message": "Token has been revoked"}), 401
                
                # PyJWT v2.0+ returns a dict directly
                data = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                current_user = User.query.filter_by(id=data.get('user_id')).first()
                
                if not current_user:
                    return jsonify({"message": "User not found"}), 401
                
                if hasattr(current_user, 'is_deleted') and current_user.is_deleted:
                    return jsonify({"message": "User account is deactivated"}), 401
                
            except jwt.ExpiredSignatureError:
                return jsonify({"message": "Token has expired"}), 401
            except jwt.InvalidTokenError:
                return jsonify({"message": "Invalid token"}), 401
            except Exception as e:
                return jsonify({"message": "Authentication error", "error": str(e)}), 401

            # Call function with or without passing current_user based on flag
            if pass_user:
                return f(current_user, *args, **kwargs)
            else:
                return f(*args, **kwargs)

        return decorated
    return decorator

def roles_allowed(*roles):
    """
    Decorator to restrict access to specific roles.
    Usage: @roles_allowed('admin', 'manager')
    """
    def wrapper(f):
        @wraps(f)
        def decorated(current_user, *args, **kwargs):
            if current_user.role not in roles:
                return jsonify({
                    "message": f"Access denied. Required roles: {list(roles)}",
                    "your_role": current_user.role
                }), 403
            return f(current_user, *args, **kwargs)
        return decorated
    return wrapper