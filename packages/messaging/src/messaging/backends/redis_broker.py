"""Redis backend: a Redis list per topic, LPUSH to publish and BRPOP to receive."""

from __future__ import annotations

from typing import Self

import redis

from messaging.broker import Broker


class RedisBroker(Broker):
    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    @classmethod
    def from_url(cls, url: str) -> Self:
        return cls(redis.Redis.from_url(url, decode_responses=True))

    def publish(self, topic: str, message: str) -> None:
        self._client.lpush(topic, message)

    def receive(self, topic: str, timeout: float = 1.0) -> str | None:
        item = self._client.brpop([topic], timeout=timeout)
        if item is None:
            return None
        value = item[1]
        return value.decode() if isinstance(value, bytes) else value

    def close(self) -> None:
        self._client.close()
