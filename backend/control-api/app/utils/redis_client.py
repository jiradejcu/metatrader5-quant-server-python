import redis
import os
from dotenv import load_dotenv

REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/1')
redis_pool = redis.ConnectionPool.from_url(REDIS_URL)

def get_redis_connection():
    return redis.Redis(connection_pool=redis_pool)