import redis.asyncio as redis
from typing import Optional
import os

# Get Redis configuration from environment variables with fallbacks
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_DB = int(os.environ.get("REDIS_DB", 0))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", None)

# Global Redis client instance
_redis_client: Optional[redis.Redis] = None

async def get_redis_client() -> redis.Redis:
    """
    Returns a Redis client instance, creating it if it doesn't exist.
    
    Returns:
        redis.Redis: An async Redis client instance
    """
    global _redis_client
    
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            decode_responses=True
        )
    
    return _redis_client

async def close_redis_connection():
    """Closes the Redis connection if it exists."""
    global _redis_client
    
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
