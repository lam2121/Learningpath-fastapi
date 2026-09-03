import asyncio
from collections import defaultdict
from threading import Lock
from typing import Any

NotificationPayload = dict[str, Any]


class NotificationStreamBroker:
    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue[NotificationPayload]]] = (
            defaultdict(set)
        )
        self._lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self) -> None:
        self._loop = asyncio.get_running_loop()

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
        with self._lock:
            queues = list(self._subscribers.get(user_id, ()))

        for queue in queues:
            await queue.put(payload)

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


notification_stream_broker = NotificationStreamBroker()
