import asyncio
from collections import defaultdict
import json
import logging
from threading import Lock
from typing import Any

from app.core.config import app_config

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

logger = logging.getLogger(__name__)

NotificationPayload = dict[str, Any]
REDIS_CHANNEL = "notifications:stream"


class NotificationStreamBroker:
    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue[NotificationPayload]]] = (
            defaultdict(set)
        )
        self._lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._redis_client: Any = None
        self._redis_task: asyncio.Task | None = None
        self._stopped: bool = False

    def attach_loop(self) -> None:
        self._loop = asyncio.get_running_loop()
        if app_config.REDIS_URL and aioredis is not None:
            if self._redis_task is None or self._redis_task.done():
                self._stopped = False
                self._redis_task = self._loop.create_task(self._redis_listener())

    async def _get_redis_client(self) -> Any:
        from app.core.redis import get_redis_async
        return get_redis_async()

    async def _redis_listener(self) -> None:
        """Background task consuming messages from Redis Pub/Sub and routing to local worker subscribers."""
        while not self._stopped:
            pubsub = None
            try:
                client = await self._get_redis_client()
                if client is None:
                    await asyncio.sleep(5)
                    continue

                pubsub = client.pubsub()
                await pubsub.subscribe(REDIS_CHANNEL)
                logger.info(f"Subscribed to Redis channel '{REDIS_CHANNEL}' for SSE notifications")

                async for message in pubsub.listen():
                    if self._stopped:
                        break
                    if message and message.get("type") == "message":
                        try:
                            raw_data = message["data"]
                            data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                            user_id = data.get("user_id")
                            payload = data.get("payload")
                            if user_id is not None and isinstance(payload, dict):
                                await self._dispatch_local(int(user_id), payload)
                        except Exception as parse_err:
                            logger.error(f"Error parsing Redis notification message: {parse_err}")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._stopped:
                    logger.warning(f"Redis Pub/Sub listener disconnected: {exc}. Reconnecting in 3s...")
                    await asyncio.sleep(3)
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.unsubscribe(REDIS_CHANNEL)
                        await pubsub.aclose()
                    except Exception:
                        pass

    async def _dispatch_local(self, user_id: int, payload: NotificationPayload) -> None:
        with self._lock:
            queues = list(self._subscribers.get(user_id, ()))
        for queue in queues:
            await queue.put(payload)

    async def subscribe(
        self, user_id: int
    ) -> asyncio.Queue[NotificationPayload]:
        queue: asyncio.Queue[NotificationPayload] = asyncio.Queue()
        with self._lock:
            self._subscribers[user_id].add(queue)
        return queue

    def unsubscribe(
        self, user_id: int, queue: asyncio.Queue[NotificationPayload]
    ) -> None:
        with self._lock:
            queues = self._subscribers.get(user_id)
            if queues is None:
                return
            queues.discard(queue)
            if not queues:
                self._subscribers.pop(user_id, None)

    async def publish(self, user_id: int, payload: NotificationPayload) -> None:
        client = await self._get_redis_client()
        if client is not None:
            try:
                message = json.dumps({"user_id": user_id, "payload": payload})
                await client.publish(REDIS_CHANNEL, message)
                return
            except Exception as exc:
                logger.warning(f"Failed to publish notification to Redis: {exc}. Falling back to local dispatch.")

        await self._dispatch_local(user_id, payload)

    async def publish_many(
        self, user_ids: list[int], payload: NotificationPayload
    ) -> None:
        unique_user_ids = list(dict.fromkeys(user_ids))
        await asyncio.gather(
            *(self.publish(user_id, payload) for user_id in unique_user_ids)
        )

    def publish_nowait(self, user_id: int, payload: NotificationPayload) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self.publish(user_id, payload), loop)

    def publish_many_nowait(
        self, user_ids: list[int], payload: NotificationPayload
    ) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self.publish_many(user_ids, payload), loop)

    async def close(self) -> None:
        self._stopped = True
        if self._redis_task is not None:
            self._redis_task.cancel()
            try:
                await self._redis_task
            except (asyncio.CancelledError, Exception):
                pass
            self._redis_task = None
        if self._redis_client is not None:
            try:
                await self._redis_client.aclose()
            except Exception:
                pass
            self._redis_client = None


notification_stream_broker = NotificationStreamBroker()
