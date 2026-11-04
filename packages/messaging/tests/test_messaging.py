import fakeredis
import pytest
from pydantic import BaseModel

from messaging import (
    InMemoryBroker,
    RedisBroker,
    broker_from_url,
    publish_event,
    receive_event,
)


class Ping(BaseModel):
    n: int


def test_in_memory_broker_is_fifo() -> None:
    broker = InMemoryBroker()
    broker.publish("t", "a")
    broker.publish("t", "b")
    assert broker.receive("t") == "a"
    assert broker.receive("t") == "b"
    assert broker.receive("t") is None


def test_topics_are_independent() -> None:
    broker = InMemoryBroker()
    broker.publish("one", "x")
    assert broker.receive("two") is None
    assert broker.pending("one") == 1


def test_redis_broker_is_fifo() -> None:
    broker = RedisBroker(fakeredis.FakeRedis(decode_responses=True))
    broker.publish("t", "a")
    broker.publish("t", "b")
    assert broker.receive("t", timeout=0.1) == "a"
    assert broker.receive("t", timeout=0.1) == "b"


def test_typed_events_round_trip() -> None:
    broker = InMemoryBroker()
    publish_event(broker, "pings", Ping(n=7))
    assert receive_event(broker, "pings", Ping) == Ping(n=7)
    assert receive_event(broker, "pings", Ping) is None


def test_broker_from_url() -> None:
    assert isinstance(broker_from_url("memory://"), InMemoryBroker)
    assert isinstance(broker_from_url("redis://localhost:6379/0"), RedisBroker)
    with pytest.raises(ValueError, match="unsupported"):
        broker_from_url("kafka://nope")
