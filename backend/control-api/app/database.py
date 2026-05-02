from flask_sqlalchemy import SQLAlchemy
import os
from dotenv import load_dotenv

load_dotenv()

# Initialize the SQLAlchemy instance without an app context yet
# This allows other modules (like models) to import 'db' safely
db = SQLAlchemy()

def init_db(app):
    """
    Configures and initializes the database for the given Flask app.
    """
    DB_USER = os.getenv('POSTGRES_USER')
    DB_PASSWORD = os.getenv('POSTGRES_PASSWORD')
    DB_NAME = os.getenv('POSTGRES_DB')
    DB_HOST = os.getenv('POSTGRES_HOST', 'postgres')

    # Constructing the URI
    if DB_PASSWORD:
        DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:5432/{DB_NAME}'
    else:
        DATABASE_URI = f'postgresql://{DB_USER}@{DB_HOST}:5432/{DB_NAME}'

    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Bind the app to the db instance
    db.init_app(app)
    
    return db