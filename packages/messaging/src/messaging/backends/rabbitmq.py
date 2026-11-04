"""RabbitMQ backend: one durable queue per topic on the default exchange.

Publishing uses persistent messages, so they survive a broker restart. Receiving
takes one message with ``basic_get`` and acknowledges it at once, which matches
the Redis backend's at-most-once BRPOP semantics.

``pika.BlockingConnection`` is not thread-safe, and FastAPI runs sync routes on a
thread pool, so every call holds a lock. If the connection has dropped (broker
restart, missed heartbeats while idle) the call reconnects and retries once.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from typing import Self

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pika.exceptions import AMQPChannelError, AMQPConnectionError

from messaging.broker import Broker

POLL_INTERVAL = 0.05  # seconds between basic_get attempts while waiting for a message

ConnectionFactory = Callable[[pika.connection.Parameters], pika.BlockingConnection]


class RabbitMQBroker(Broker):
    def __init__(
        self,
        parameters: pika.connection.Parameters,
        connection_factory: ConnectionFactory = pika.BlockingConnection,
    ) -> None:
        self._parameters = parameters
        self._connect = connection_factory
        self._connection: pika.BlockingConnection | None = None
        self._channel: BlockingChannel | None = None
        self._declared: set[str] = set()
        self._lock = threading.Lock()

    @classmethod
    def from_url(cls, url: str) -> Self:
        return cls(pika.URLParameters(url))

    # ------------------------------------------------------------------ Broker

    def publish(self, topic: str, message: str) -> None:
        properties = pika.BasicProperties(
            content_type="application/json",
            delivery_mode=pika.DeliveryMode.Persistent,
        )

        def op(channel: BlockingChannel) -> None:
            self._declare(channel, topic)
            channel.basic_publish(
                exchange="", routing_key=topic, body=message.encode(), properties=properties
            )

        self._run(op)

    def receive(self, topic: str, timeout: float = 1.0) -> str | None:
        def op(channel: BlockingChannel) -> str | None:
            self._declare(channel, topic)
            deadline = time.monotonic() + timeout
            while True:
                _method, _properties, body = channel.basic_get(queue=topic, auto_ack=True)
                if body is not None:
                    return bytes(body).decode()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                # Sleeps while still servicing heartbeats on this connection.
                assert self._connection is not None
                self._connection.process_data_events(time_limit=min(POLL_INTERVAL, remaining))

        return self._run(op)

    def close(self) -> None:
        with self._lock:
            self._reset()

    # ---------------------------------------------------------------- helpers

    def _run[T](self, op: Callable[[BlockingChannel], T]) -> T:
        with self._lock:
            try:
                return op(self._ensure_channel())
            except (AMQPConnectionError, AMQPChannelError):
                self._reset()
                return op(self._ensure_channel())

    def _ensure_channel(self) -> BlockingChannel:
        if self._connection is None or self._connection.is_closed:
            self._connection = self._connect(self._parameters)
            self._channel = None
        if self._channel is None or self._channel.is_closed:
            self._channel = self._connection.channel()
            self._declared.clear()
        return self._channel

    def _declare(self, channel: BlockingChannel, topic: str) -> None:
        if topic not in self._declared:
            channel.queue_declare(queue=topic, durable=True)
            self._declared.add(topic)

    def _reset(self) -> None:
        connection, self._connection, self._channel = self._connection, None, None
        self._declared.clear()
        if connection is not None and connection.is_open:
            with contextlib.suppress(Exception):  # already broken; nothing useful to do
                connection.close()
