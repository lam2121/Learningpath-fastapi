import logging
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import app_config

logger = logging.getLogger(__name__)

# Point SlowAPI to Redis if REDIS_URL is configured, else fallback to memory://
storage_uri = app_config.REDIS_URL.strip() if app_config.REDIS_URL and app_config.REDIS_URL.strip() else "memory://"

try:
    limiter = Limiter(
        key_func=get_remote_address,
        storage_uri=storage_uri,
    )
except Exception as exc:
    logger.warning(f"[SlowAPI] Failed to initialize storage with '{storage_uri}': {exc}. Falling back to memory://")
    limiter = Limiter(
        key_func=get_remote_address,
        storage_uri="memory://",
    )

