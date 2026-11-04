"""The transport-neutral broker interface and the URL-based backend registry.

Services only ever see :class:`Broker`. Which technology moves the bytes (Redis,
RabbitMQ, a plain TCP broker, process memory, ...) is chosen at start-up from a
URL, normally the ``BROKER_URL`` environment variable::

    memory://                              in-process, for tests
    redis://redis:6379/0                   Redis list (needs messaging[redis])
    amqp://guest:guest@rabbitmq:5672/      RabbitMQ queue (needs messaging[rabbitmq])
    tcp://tcp-broker:7000                  the stdlib-only TCP broker (apps/tcp-broker)

A broker moves opaque string messages through named topics. Each message is
delivered to exactly one consumer (work-queue semantics), so running more
worker replicas spreads the load instead of duplicating work.
"""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from collections.abc import Callable
from types import TracebackType
from typing import Self
from urllib.parse import urlsplit


class BrokerError(Exception):
    """Raised for configuration problems, such as an unknown or uninstalled backend."""


class Broker(ABC):
    """What every transport must provide. Application code depends on this alone."""

    @abstractmethod
    def publish(self, topic: str, message: str) -> None:
        """Enqueue ``message`` on ``topic``."""

    @abstractmethod
    def receive(self, topic: str, timeout: float = 1.0) -> str | None:
        """Return the next message on ``topic``, or ``None`` after ``timeout`` seconds."""

    def close(self) -> None:  # noqa: B027 - optional hook, most backends need nothing
        """Release network resources. Safe to call more than once."""

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


BrokerFactory = Callable[[str], Broker]

# scheme -> "module:Class" (imported lazily so a missing optional client library only
# matters when that backend is actually selected), or a factory registered at runtime.
_BACKENDS: dict[str, str | BrokerFactory] = {
    "memory": "messaging.backends.memory:InMemoryBroker",
    "redis": "messaging.backends.redis_broker:RedisBroker",
    "rediss": "messaging.backends.redis_broker:RedisBroker",
    "amqp": "messaging.backends.rabbitmq:RabbitMQBroker",
    "amqps": "messaging.backends.rabbitmq:RabbitMQBroker",
    "tcp": "messaging.backends.tcp:TcpBroker",
}

# Which optional extra provides the client library for a backend module.
_EXTRAS = {"redis_broker": "redis", "rabbitmq": "rabbitmq"}


def register_backend(scheme: str, factory: BrokerFactory) -> None:
    """Plug in another transport (Kafka, NATS, SQS, ...) without touching this package.

    ``factory`` receives the full URL and returns a :class:`Broker`.
    """
    _BACKENDS[scheme.lower()] = factory


def available_schemes() -> list[str]:
    return sorted(_BACKENDS)


def _load(target: str) -> BrokerFactory:
    module_name, _, attr = target.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        extra = _EXTRAS.get(module_name.rsplit(".", 1)[-1], "")
        raise BrokerError(
            f"the client library for this broker is not installed ({exc.name}); "
            f"install the `messaging[{extra}]` extra (or the app's `{extra}` extra)"
        ) from exc
    cls = getattr(module, attr)
    factory: BrokerFactory = cls.from_url
    return factory


def broker_from_url(url: str) -> Broker:
    """Build the broker a URL names, e.g. ``broker_from_url(settings.broker_url)``."""
    scheme = urlsplit(url).scheme.lower()
    target = _BACKENDS.get(scheme)
    if target is None:
        raise BrokerError(
            f"unsupported broker URL {url!r}; known schemes: {', '.join(available_schemes())}"
        )
    factory = _load(target) if isinstance(target, str) else target
    return factory(url)
