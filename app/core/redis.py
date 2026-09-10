"""Production-grade Redis caching & connection management module.

Features:
- Dual async/sync connection pools with socket timeout (2.0s).
- Graceful degradation: all cache operations catch exceptions, log warnings,
  and fail silently so MySQL remains the single source of truth and requests
  never fail with 500 when Redis is offline or degraded.
- Support for JSON serialization/deserialization.
- Support for redis:// and SSL rediss:// schemas via app_config.REDIS_URL.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.core.config import app_config

try:
    import redis
    import redis.asyncio as aioredis
except ImportError:
    redis = None
    aioredis = None

logger = logging.getLogger(__name__)

# Connection singletons
_async_redis_client: Optional[aioredis.Redis] = None
_sync_redis_client: Optional[redis.Redis] = None


def get_redis_async() -> Optional[aioredis.Redis]:
    """Get or create singleton async Redis client with 2s timeout."""
    global _async_redis_client
    if not app_config.REDIS_URL or aioredis is None:
        return None

    if _async_redis_client is None:
        try:
            _async_redis_client = aioredis.from_url(
                app_config.REDIS_URL,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                retry_on_timeout=True,
            )
        except Exception as exc:
            logger.warning(f"[Redis Async] Connection initialization failed: {exc}")
            return None
    return _async_redis_client


def get_redis_sync() -> Optional[redis.Redis]:
    """Get or create singleton synchronous Redis client with 2s timeout."""
    global _sync_redis_client
    if not app_config.REDIS_URL or redis is None:
        return None

    if _sync_redis_client is None:
        try:
            _sync_redis_client = redis.from_url(
                app_config.REDIS_URL,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                retry_on_timeout=True,
            )
        except Exception as exc:
            logger.warning(f"[Redis Sync] Connection initialization failed: {exc}")
            return None
    return _sync_redis_client


# ── Async Cache Helpers ───────────────────────────────────────────────────────

async def async_get_cache(key: str) -> Any | None:
    """Retrieve and deserialize a JSON cached value. Returns None on cache miss or error."""
    client = get_redis_async()
    if client is None:
        return None
    try:
        raw = await client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw
    except Exception as exc:
        logger.warning(f"[Redis Cache] async_get_cache('{key}') failed: {exc}")
        return None


async def async_set_cache(key: str, value: Any, ttl_seconds: int = 300) -> bool:
    """Serialize and store a value with TTL. Returns False on failure without raising."""
    client = get_redis_async()
    if client is None:
        return False
    try:
        data = value if isinstance(value, str) else json.dumps(value, default=str)
        await client.set(key, data, ex=ttl_seconds)
        return True
    except Exception as exc:
        logger.warning(f"[Redis Cache] async_set_cache('{key}') failed: {exc}")
        return False


async def async_delete_cache(key: str) -> bool:
    """Delete a key from Redis. Returns False on failure."""
    client = get_redis_async()
    if client is None:
        return False
    try:
        await client.delete(key)
        return True
    except Exception as exc:
        logger.warning(f"[Redis Cache] async_delete_cache('{key}') failed: {exc}")
        return False


async def async_delete_cache_pattern(pattern: str) -> int:
    """Delete all keys matching a glob pattern using SCAN. Returns count deleted."""
    client = get_redis_async()
    if client is None:
        return 0
    try:
        deleted_count = 0
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                deleted_count += await client.delete(*keys)
            if cursor == 0:
                break
        return deleted_count
    except Exception as exc:
        logger.warning(f"[Redis Cache] async_delete_cache_pattern('{pattern}') failed: {exc}")
        return 0


# ── Sync Cache Helpers (For threadpool / synchronous ORM endpoints) ───────────

def sync_get_cache(key: str) -> Any | None:
    """Synchronously retrieve and deserialize a JSON cached value."""
    client = get_redis_sync()
    if client is None:
        return None
    try:
        raw = client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw
    except Exception as exc:
        logger.warning(f"[Redis Cache Sync] sync_get_cache('{key}') failed: {exc}")
        return None


def sync_set_cache(key: str, value: Any, ttl_seconds: int = 300) -> bool:
    """Synchronously serialize and store a value with TTL."""
    client = get_redis_sync()
    if client is None:
        return False
    try:
        data = value if isinstance(value, str) else json.dumps(value, default=str)
        client.set(key, data, ex=ttl_seconds)
        return True
    except Exception as exc:
        logger.warning(f"[Redis Cache Sync] sync_set_cache('{key}') failed: {exc}")
        return False


def sync_delete_cache(key: str) -> bool:
    """Synchronously delete a key from Redis."""
    client = get_redis_sync()
    if client is None:
        return False
    try:
        client.delete(key)
        return True
    except Exception as exc:
        logger.warning(f"[Redis Cache Sync] sync_delete_cache('{key}') failed: {exc}")
        return False


def sync_delete_cache_pattern(pattern: str) -> int:
    """Synchronously delete all keys matching a glob pattern using SCAN."""
    client = get_redis_sync()
    if client is None:
        return 0
    try:
        deleted_count = 0
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                deleted_count += client.delete(*keys)
            if cursor == 0:
                break
        return deleted_count
    except Exception as exc:
        logger.warning(f"[Redis Cache Sync] sync_delete_cache_pattern('{pattern}') failed: {exc}")
        return 0
