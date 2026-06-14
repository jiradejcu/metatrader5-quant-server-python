import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_db_connection():
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'postgres'),
        port=os.getenv('POSTGRES_PORT', '5432'),
        dbname=os.getenv('POSTGRES_DB'),
        user=os.getenv('POSTGRES_USER'),
        password=os.getenv('POSTGRES_PASSWORD'),
    )
