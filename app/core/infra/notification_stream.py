import asyncio
import logging
from collections import defaultdict
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

NotificationPayload = dict[str, Any]
DEFAULT_QUEUE_MAXSIZE: int = 50


class NotificationStreamBroker:
    """In-memory event broker for server-sent events (SSE).
    
    Features:
    - Bounded queues per client (maxsize=50) to prevent memory leaks / OOM.
    - Drops oldest messages when consumer is slow (Drop Oldest policy).
    - Immediate memory reclamation on unsubscribe and explicit drain support.
    """

    def __init__(self, default_maxsize: int = DEFAULT_QUEUE_MAXSIZE) -> None:
        self._default_maxsize = default_maxsize
        self._subscribers: dict[int, set[asyncio.Queue[NotificationPayload]]] = (
            defaultdict(set)
        )
        self._lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self) -> None:
        self._loop = asyncio.get_running_loop()

    async def subscribe(
        self, user_id: int, maxsize: int | None = None
    ) -> asyncio.Queue[NotificationPayload]:
        queue_size = maxsize or self._default_maxsize
        queue: asyncio.Queue[NotificationPayload] = asyncio.Queue(maxsize=queue_size)
        with self._lock:
            self._subscribers[user_id].add(queue)
        return queue

    def unsubscribe(
        self, user_id: int, queue: asyncio.Queue[NotificationPayload]
    ) -> None:
        with self._lock:
            queues = self._subscribers.get(user_id)
            if queues is not None:
                queues.discard(queue)
                if not queues:
                    self._subscribers.pop(user_id, None)

        # Clear and drain all remaining messages from the disconnected queue immediately
        self._drain_queue(queue)

    @staticmethod
    def _drain_queue(queue: asyncio.Queue[NotificationPayload]) -> int:
        """Discard all pending messages from a queue, immediately reclaiming memory."""
        drained = 0
        while not queue.empty():
            try:
                queue.get_nowait()
                drained += 1
            except asyncio.QueueEmpty:
                break
        return drained

    def drain_user_queues(self, user_id: int) -> int:
        """Purge all pending messages across all active queues for a specific user."""
        with self._lock:
            queues = list(self._subscribers.get(user_id, ()))
        return sum(self._drain_queue(q) for q in queues)

    @staticmethod
    def _push_drop_oldest(
        queue: asyncio.Queue[NotificationPayload], payload: NotificationPayload
    ) -> None:
        """Push payload to bounded queue. If queue is full, drop oldest unread message."""
        while queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            # Fallback for concurrent writers
            try:
                queue.get_nowait()
                queue.put_nowait(payload)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    async def publish(self, user_id: int, payload: NotificationPayload) -> None:
        with self._lock:
            queues = list(self._subscribers.get(user_id, ()))

        for queue in queues:
            self._push_drop_oldest(queue, payload)

    async def publish_many(
        self, user_ids: list[int], payload: NotificationPayload
    ) -> None:
        unique_user_ids = list(dict.fromkeys(user_ids))
        for user_id in unique_user_ids:
            await self.publish(user_id, payload)

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
        """Clear all active subscriber queues on shutdown."""
        with self._lock:
            for queues in self._subscribers.values():
                for q in queues:
                    self._drain_queue(q)
            self._subscribers.clear()


notification_stream_broker = NotificationStreamBroker()
