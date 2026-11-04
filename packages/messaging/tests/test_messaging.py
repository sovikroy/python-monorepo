"""Behaviour every transport must share. Each test runs once per backend."""

import threading

import pytest
from pydantic import BaseModel

from messaging import Broker, InMemoryBroker, publish_event, receive_event


class Ping(BaseModel):
    n: int


def drain(broker: Broker, topic: str, count: int) -> list[str]:
    out: list[str] = []
    for _ in range(count):
        message = broker.receive(topic, timeout=2)
        assert message is not None
        out.append(message)
    return out


def test_fifo(any_broker: Broker, topic: str) -> None:
    for message in ("a", "b", "c"):
        any_broker.publish(topic, message)
    assert drain(any_broker, topic, 3) == ["a", "b", "c"]
    assert any_broker.receive(topic, timeout=0.1) is None


def test_empty_topic_times_out(any_broker: Broker, topic: str) -> None:
    assert any_broker.receive(topic, timeout=0.1) is None


def test_topics_are_independent(any_broker: Broker, topic: str) -> None:
    any_broker.publish(topic, "x")
    assert any_broker.receive(f"{topic}.other", timeout=0.1) is None
    assert any_broker.receive(topic, timeout=1) == "x"


def test_non_ascii_and_large_messages(any_broker: Broker, topic: str) -> None:
    big = "é✓" * 100_000
    any_broker.publish(topic, big)
    assert any_broker.receive(topic, timeout=2) == big


def test_typed_events_round_trip(any_broker: Broker, topic: str) -> None:
    publish_event(any_broker, topic, Ping(n=7))
    assert receive_event(any_broker, topic, Ping, timeout=2) == Ping(n=7)
    assert receive_event(any_broker, topic, Ping, timeout=0.1) is None


def test_concurrent_publishers(any_broker: Broker, topic: str) -> None:
    """FastAPI calls publish from several threads at once."""

    def publish_many(prefix: str) -> None:
        for i in range(20):
            any_broker.publish(topic, f"{prefix}{i}")

    threads = [threading.Thread(target=publish_many, args=(p,)) for p in "abcd"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    expected = sorted(f"{p}{i}" for p in "abcd" for i in range(20))
    assert sorted(drain(any_broker, topic, 80)) == expected


def test_close_is_idempotent(any_broker: Broker) -> None:
    any_broker.close()
    any_broker.close()


def test_in_memory_pending() -> None:
    broker = InMemoryBroker()
    broker.publish("one", "x")
    assert broker.pending("one") == 1
    assert broker.pending("two") == 0


@pytest.mark.parametrize("payload", ["", "line\nbreak"])
def test_awkward_payloads(any_broker: Broker, topic: str, payload: str) -> None:
    any_broker.publish(topic, payload)
    assert any_broker.receive(topic, timeout=2) == payload
