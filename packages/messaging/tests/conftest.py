"""Fixtures that hand every contract test each available transport.

memory, Redis (via fakeredis) and TCP (a real server on a random port) always run.
Real Redis and RabbitMQ servers join in when their URL is set, as CI's integration
job does:

    MESSAGING_TEST_REDIS_URL=redis://localhost:6379/0
    MESSAGING_TEST_AMQP_URL=amqp://guest:guest@localhost:5672/
"""

import os
import threading
import uuid
from collections.abc import Iterator

import fakeredis
import pytest

from messaging import Broker, InMemoryBroker, broker_from_url
from messaging.backends.redis_broker import RedisBroker
from messaging.backends.tcp import TcpBrokerServer

REDIS_URL = os.environ.get("MESSAGING_TEST_REDIS_URL")
AMQP_URL = os.environ.get("MESSAGING_TEST_AMQP_URL")


@pytest.fixture
def tcp_server() -> Iterator[TcpBrokerServer]:
    server = TcpBrokerServer("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture(
    params=[
        "memory",
        "fakeredis",
        "tcp",
        pytest.param(
            "redis",
            marks=pytest.mark.skipif(not REDIS_URL, reason="MESSAGING_TEST_REDIS_URL not set"),
        ),
        pytest.param(
            "rabbitmq",
            marks=pytest.mark.skipif(not AMQP_URL, reason="MESSAGING_TEST_AMQP_URL not set"),
        ),
    ]
)
def any_broker(request: pytest.FixtureRequest) -> Iterator[Broker]:
    """A connected broker of each kind. Use :func:`topic` for an isolated topic name."""
    kind: str = request.param
    broker: Broker
    if kind == "memory":
        broker = InMemoryBroker()
    elif kind == "fakeredis":
        broker = RedisBroker(fakeredis.FakeRedis(decode_responses=True))
    elif kind == "tcp":
        server: TcpBrokerServer = request.getfixturevalue("tcp_server")
        broker = broker_from_url(f"tcp://127.0.0.1:{server.port}")
    elif kind == "redis":
        assert REDIS_URL
        broker = broker_from_url(REDIS_URL)
    else:
        assert AMQP_URL
        broker = broker_from_url(AMQP_URL)
    with broker:
        yield broker


@pytest.fixture
def topic() -> str:
    """A fresh topic per test, so runs against a shared real broker don't interfere."""
    return f"test.{uuid.uuid4().hex}"
