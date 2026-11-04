"""Process-local broker for tests and single-process experiments."""

from __future__ import annotations

import threading
from collections import deque
from typing import Self

from messaging.broker import Broker


class InMemoryBroker(Broker):
    """Queues live in this process, so it cannot connect two containers.

    ``receive`` never blocks: it returns ``None`` straight away when the topic is
    empty, which keeps tests that poll an empty queue fast.
    """

    def __init__(self) -> None:
        self._queues: dict[str, deque[str]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_url(cls, url: str) -> Self:
        return cls()

    def publish(self, topic: str, message: str) -> None:
        with self._lock:
            self._queues.setdefault(topic, deque()).append(message)

    def receive(self, topic: str, timeout: float = 1.0) -> str | None:
        with self._lock:
            queue = self._queues.get(topic)
            return queue.popleft() if queue else None

    def pending(self, topic: str) -> int:
        with self._lock:
            return len(self._queues.get(topic, ()))
