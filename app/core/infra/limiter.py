import logging
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.infra.config import app_config

logger = logging.getLogger(__name__)


def _create_limiter() -> Limiter:
    """Create a unified Limiter instance.

    Uses Redis storage if REDIS_URL is provided and redis client is available.
    Supports redis:// and rediss:// (TLS) storage schemes.
    Otherwise safely falls back to in-memory storage.
    """
    redis_url = (getattr(app_config, "REDIS_URL", None) or "").strip()
    if redis_url:
        try:
            import redis  # noqa: F401
            return Limiter(key_func=get_remote_address, storage_uri=redis_url)
        except Exception as exc:
            logger.warning(
                "Redis rate-limit storage requested at '%s' but unavailable (%s). "
                "Falling back to in-memory limiter storage.",
                redis_url,
                exc,
            )
    return Limiter(key_func=get_remote_address, storage_uri="memory://")


limiter = _create_limiter()
