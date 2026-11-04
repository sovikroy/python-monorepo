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

# Real servers the contract tests also run against: backend -> env var holding its URL.
# Each one is skipped unless its variable is set. The new-broker skill adds entries here.
REAL_BROKERS = {
    "redis": "MESSAGING_TEST_REDIS_URL",
    "rabbitmq": "MESSAGING_TEST_AMQP_URL",
}


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
        *(
            pytest.param(
                kind,
                marks=pytest.mark.skipif(not os.environ.get(var), reason=f"{var} not set"),
            )
            for kind, var in REAL_BROKERS.items()
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
    else:
        broker = broker_from_url(os.environ[REAL_BROKERS[kind]])
    with broker:
        yield broker


@pytest.fixture
def topic() -> str:
    """A fresh topic per test, so runs against a shared real broker don't interfere."""
    return f"test.{uuid.uuid4().hex}"
