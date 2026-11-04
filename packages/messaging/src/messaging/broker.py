"""Broker implementations.

A broker moves opaque string messages through named topics. Each message is
delivered to exactly one consumer (work-queue semantics), so running more
worker replicas spreads the load instead of duplicating work.
"""

from collections import deque
from typing import Protocol

import redis


class Broker(Protocol):
    def publish(self, topic: str, message: str) -> None: ...

    def receive(self, topic: str, timeout: float = 1.0) -> str | None:
        """Return the next message on ``topic``, or ``None`` after ``timeout`` seconds."""
        ...


class InMemoryBroker:
    """Process-local broker for tests and local experiments."""

    def __init__(self) -> None:
        self._queues: dict[str, deque[str]] = {}

    def publish(self, topic: str, message: str) -> None:
        self._queues.setdefault(topic, deque()).append(message)

    def receive(self, topic: str, timeout: float = 1.0) -> str | None:
        queue = self._queues.get(topic)
        return queue.popleft() if queue else None

    def pending(self, topic: str) -> int:
        return len(self._queues.get(topic, ()))


class RedisBroker:
    """Redis list used as a FIFO queue: LPUSH to publish, BRPOP to receive."""

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    @classmethod
    def from_url(cls, url: str) -> "RedisBroker":
        return cls(redis.Redis.from_url(url, decode_responses=True))

    def publish(self, topic: str, message: str) -> None:
        self._client.lpush(topic, message)

    def receive(self, topic: str, timeout: float = 1.0) -> str | None:
        item = self._client.brpop([topic], timeout=timeout)
        if item is None:
            return None
        value = item[1]
        return value.decode() if isinstance(value, bytes) else value


def broker_from_url(url: str) -> Broker:
    """Build a broker from a URL such as ``memory://`` or ``redis://host:6379/0``."""
    if url.startswith("memory://"):
        return InMemoryBroker()
    if url.startswith(("redis://", "rediss://")):
        return RedisBroker.from_url(url)
    raise ValueError(f"unsupported broker URL: {url!r}")
