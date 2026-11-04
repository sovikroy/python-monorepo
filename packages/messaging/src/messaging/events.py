"""Typed helpers that (de)serialise pydantic models on top of a :class:`Broker`."""

from pydantic import BaseModel

from messaging.broker import Broker


def publish_event(broker: Broker, topic: str, event: BaseModel) -> None:
    broker.publish(topic, event.model_dump_json())


def receive_event[E: BaseModel](
    broker: Broker, topic: str, event_type: type[E], timeout: float = 1.0
) -> E | None:
    raw = broker.receive(topic, timeout=timeout)
    return None if raw is None else event_type.model_validate_json(raw)
