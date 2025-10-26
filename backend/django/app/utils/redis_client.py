import redis
from django.conf import settings
redis_pool = redis.ConnectionPool.from_url(settings.REDIS_URL)

def get_redis_connection():
    return redis.Redis(connection_pool=redis_pool)