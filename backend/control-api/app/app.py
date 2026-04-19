from flask import Flask, jsonify
from dotenv import load_dotenv
from flask_cors import CORS
import os
from werkzeug.middleware.proxy_fix import ProxyFix
import logging
import sys
from sqlalchemy.sql import text
from database import db, init_db

# Routes
from routes.control import control_bp
from routes.user import user_bp

# Models
from models.user import User

load_dotenv()
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def create_app():
    app = Flask(__name__)
    allowed_origin = [
    'https://arbitrage-monitor.vatanutanon.me',
    ]

    CORS(app, resources={r"/*": {'origins': allowed_origin}})

    app.config['PREFERRED_URL_SCHEME'] = 'https'

    app.register_blueprint(control_bp)
    app.register_blueprint(user_bp)

    # ทำให้ communicate between user and server (Docker, external)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # Initial database
    init_db(app)

    @app.route('/')
    def hello():
        return 'Hello, Arbitrage!'
    
    return app

if __name__ == '__main__':
    app = create_app()

    app.run(host='0.0.0.0', port=int(os.environ.get('CONTROL_API_PORT')))