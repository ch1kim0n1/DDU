"""Session event fan-out for one or many API workers."""

from __future__ import annotations

import asyncio
import json
import os
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any


class SessionEventBus:
    def __init__(self) -> None:
        self.redis_url = os.environ.get("MIRROR_REDIS_URL", "").strip()
        self._queues: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    @property
    def backend_name(self) -> str:
        return "redis-pubsub" if self.redis_url else "in-process"

    @staticmethod
    def _channel(session_id: str) -> str:
        return f"ddu:mirror:events:{session_id}"

    async def publish(
        self,
        session_id: str,
        event: str,
        *,
        snapshot: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        request_id: str = "",
    ) -> None:
        message = {
            "event": event,
            "session_id": session_id,
            "snapshot": snapshot,
            "payload": payload or {},
            "request_id": request_id,
        }
        if self.redis_url:
            from redis.asyncio import Redis

            client = Redis.from_url(self.redis_url, decode_responses=True)
            try:
                await client.publish(
                    self._channel(session_id),
                    json.dumps(message, separators=(",", ":"), default=str),
                )
            finally:
                await client.aclose()
            return
        for queue in list(self._queues.get(session_id, ())):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(message)

    async def subscribe(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        if self.redis_url:
            from redis.asyncio import Redis

            client = Redis.from_url(self.redis_url, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe(self._channel(session_id))
            try:
                while True:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=15.0
                    )
                    if message and message.get("data"):
                        yield json.loads(message["data"])
                    else:
                        yield {"event": "session.keepalive", "session_id": session_id}
            finally:
                await pubsub.unsubscribe(self._channel(session_id))
                await pubsub.aclose()
                await client.aclose()
            return

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._queues[session_id].add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._queues[session_id].discard(queue)
            if not self._queues[session_id]:
                self._queues.pop(session_id, None)

    async def healthy(self) -> bool:
        if not self.redis_url:
            return True
        from redis.asyncio import Redis

        client = Redis.from_url(self.redis_url, decode_responses=True)
        try:
            return bool(await client.ping())
        except Exception:
            return False
        finally:
            await client.aclose()


event_bus = SessionEventBus()
