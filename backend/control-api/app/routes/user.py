from flask import Blueprint, jsonify, request
import logging
import os
import datetime
from datetime import timezone, timedelta
from dotenv import load_dotenv

from database import db
from models.user import User
from werkzeug.security import generate_password_hash, check_password_hash
from utils.authetication import token_required, roles_allowed
from utils.redis_client import get_redis_connection
import jwt


load_dotenv()

logger = logging.getLogger(__name__)
user_bp = Blueprint('user', __name__)

ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
TEST_PASSWORD = os.getenv('TEST_PASSWORD')
SECRET_KEY = os.getenv('SECRET_KEY')
INIT_DB_SECRET = os.getenv('INIT_DB_SECRET')
ALGORITHM = "HS256"

@user_bp.route('/init-db', methods=['POST'])
def initialize_db():
        if not INIT_DB_SECRET:
            return jsonify({"message": "Init endpoint is disabled"}), 403

        data = request.get_json() or {}
        if data.get('secret') != INIT_DB_SECRET:
            return jsonify({"message": "Invalid secret"}), 403

        try:
            # Create tables if they don't exist
            db.create_all()

            # Check if we already have an admin to avoid duplicates
            admin_exists = User.query.filter_by(username='admin').first()
            
            if not admin_exists:
                # Use generate_password_hash to store a secure salted hash
                hashed = generate_password_hash(ADMIN_PASSWORD, method='pbkdf2:sha256')
                
                admin_user = User(
                    username="admin",
                    password=hashed, 
                    display_name="Administrator",
                    is_deleted=False,
                    role='admin'
                )
                
                # Add a standard user for testing the login flow
                user_hashed = generate_password_hash(TEST_PASSWORD, method='pbkdf2:sha256')
                test_user = User(
                    username='test01',
                    password=user_hashed,
                    display_name='test01',
                    is_deleted=False,
                    role='user'
                )

                db.session.add(admin_user)
                db.session.add(test_user)
                db.session.commit()
                
                return jsonify({
                    "message": "Database initialized successfully with hashed passwords.",
                    "users_created": ["admin", "testuser"]
                }), 201
            
            return jsonify({"message": "Database already contains seed data."}), 200

        except Exception as e:
            db.session.rollback()
            return jsonify({
                "message": "Failed to initialize database",
                "error": str(e)
            }), 500

@user_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()

    if not data or not data.get('username') or not data.get('password'):
        return jsonify({"message": "Credentials required"}), 400

    user = User.query.filter_by(username=data.get('username')).first()

    if not user or (hasattr(user, 'is_deleted') and user.is_deleted):
        return jsonify({"message": "Invalid username or password"}), 401

    if check_password_hash(user.password, data.get('password')):
        payload = {
            'user_id': user.id,
            'username': user.username,
            'role': user.role,
            'exp': datetime.datetime.now(timezone.utc) + timedelta(hours=24)
        }
        
        token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
        
        # PyJWT v2+ returns a string, so no .decode('utf-8') needed
        return jsonify({
            "message": "Login successful",
            "access_token": token,
            "user": user.to_dict()
        }), 200

    return jsonify({"message": "Invalid username or password"}), 401

@user_bp.route('/me', methods=['GET'])
@token_required(pass_user= True)
def get_my_profile(current_user):
    return jsonify({
        "status": "success",
        "data": current_user.to_dict()
    }), 200

@user_bp.route('/users/<string:user_id>', methods=['DELETE'])
@token_required(pass_user= True)
@roles_allowed('admin')  # Only admins can delete users
def delete_user(current_user, user_id):
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({"message": "User not found"}), 404

        user.is_deleted = True
        user.delete_time = datetime.datetime.now(timezone.utc)
        db.session.commit()
        
        return jsonify({"message": f"User {user_id} soft-deleted."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@user_bp.route('/verify-token', methods=['GET'])
@token_required(pass_user= True)
def verify_token(current_user):
    """
    Endpoint for the frontend to check if the token in localStorage is valid.
    If @token_required passes, it means the token is valid.
    """
    return jsonify({
        "status": "valid",
        "message": "Token is active",
        "user": current_user.to_dict()
    }), 200

@user_bp.route('/logout', methods=['POST'])
@token_required(pass_user= True)
def logout(current_user):
    """
    Logout endpoint to blacklist the current token.
    Requires valid token in Authorization header.
    """
    try:
        # Extract token from Authorization header
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({"message": "Token format is 'Bearer <token>'"}), 401
        
        if not token:
            return jsonify({"message": "Token is missing"}), 401
        
        # Decode token to get expiration time
        data = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        exp_timestamp = data.get('exp')
        
        # Add token to blacklist with TTL equal to token expiration time
        redis_conn = get_redis_connection()
        if exp_timestamp:
            ttl = exp_timestamp - datetime.datetime.now(timezone.utc).timestamp()
            if ttl > 0:
                redis_conn.setex(f"blacklist:{token}", int(ttl), "revoked")
        
        return jsonify({
            "status": "success",
            "message": f"User {current_user.username} logged out successfully",
            "user_id": current_user.id
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Error handler for 401 within this blueprint
@user_bp.errorhandler(401)
def unauthorized(error):
    return jsonify({"status": "Unauthorized", "message": str(error)}), 401