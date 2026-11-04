"""Publish and consume typed events through a pluggable broker.

Application code depends only on :class:`Broker` and the typed helpers. The
transport is picked at start-up from a URL (``BROKER_URL``)::

    broker = broker_from_url("amqp://guest:guest@rabbitmq:5672/")

See :mod:`messaging.broker` for the supported schemes and how to add one.
"""

from messaging.backends.memory import InMemoryBroker
from messaging.broker import (
    Broker,
    BrokerError,
    BrokerFactory,
    available_schemes,
    broker_from_url,
    register_backend,
)
from messaging.events import publish_event, receive_event

__all__ = [
    "Broker",
    "BrokerError",
    "BrokerFactory",
    "InMemoryBroker",
    "available_schemes",
    "broker_from_url",
    "publish_event",
    "receive_event",
    "register_backend",
]
