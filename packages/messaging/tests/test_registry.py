import pytest

from messaging import (
    Broker,
    BrokerError,
    InMemoryBroker,
    available_schemes,
    broker_from_url,
    register_backend,
)
from messaging.backends.rabbitmq import RabbitMQBroker
from messaging.backends.redis_broker import RedisBroker
from messaging.backends.tcp import TcpBroker
from messaging.broker import _BACKENDS


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("memory://", InMemoryBroker),
        ("redis://localhost:6379/0", RedisBroker),
        ("rediss://localhost:6380/0", RedisBroker),
        ("amqp://guest:guest@localhost:5672/", RabbitMQBroker),
        ("AMQP://localhost", RabbitMQBroker),
        ("tcp://localhost:7000", TcpBroker),
        ("tcp://localhost", TcpBroker),
    ],
)
def test_url_scheme_selects_backend(url: str, kind: type[Broker]) -> None:
    # Building a broker never connects; the first publish/receive does.
    with broker_from_url(url) as broker:
        assert isinstance(broker, kind)


def test_unknown_scheme_lists_the_known_ones() -> None:
    with pytest.raises(BrokerError, match=r"unsupported.*amqp.*tcp"):
        broker_from_url("kafka://nope")


def test_tcp_url_needs_a_host() -> None:
    with pytest.raises(BrokerError, match="needs a host"):
        broker_from_url("tcp://")


def test_register_custom_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(_BACKENDS, "custom", _BACKENDS["memory"])
    created: list[str] = []

    def factory(url: str) -> Broker:
        created.append(url)
        return InMemoryBroker()

    register_backend("Custom", factory)
    assert "custom" in available_schemes()
    assert isinstance(broker_from_url("custom://x"), InMemoryBroker)
    assert created == ["custom://x"]


def test_missing_client_library_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(_BACKENDS, "ghost", "messaging.backends.not_installed:Nope")
    with pytest.raises(BrokerError, match="not installed"):
        broker_from_url("ghost://x")


def test_missing_rabbitmq_extra_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.delitem(sys.modules, "messaging.backends.rabbitmq", raising=False)
    monkeypatch.setitem(sys.modules, "pika", None)  # makes `import pika` fail
    with pytest.raises(BrokerError, match=r"messaging\[rabbitmq\]"):
        broker_from_url("amqp://localhost")
