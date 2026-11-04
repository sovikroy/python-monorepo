"""RabbitMQ-specific behaviour. Needs a real server (CI's integration job provides one)."""

import os

import pytest

from messaging import broker_from_url
from messaging.backends.rabbitmq import RabbitMQBroker

AMQP_URL = os.environ.get("MESSAGING_TEST_AMQP_URL")

pytestmark = pytest.mark.skipif(not AMQP_URL, reason="MESSAGING_TEST_AMQP_URL not set")


def test_reconnects_after_the_connection_drops(topic: str) -> None:
    assert AMQP_URL
    with broker_from_url(AMQP_URL) as broker:
        assert isinstance(broker, RabbitMQBroker)
        broker.publish(topic, "one")
        assert broker._connection is not None
        broker._connection.close()  # as if the broker restarted or heartbeats lapsed
        broker.publish(topic, "two")
        assert broker.receive(topic, timeout=2) == "one"
        assert broker.receive(topic, timeout=2) == "two"


def test_messages_wait_in_a_durable_queue_for_a_later_consumer(topic: str) -> None:
    assert AMQP_URL
    with broker_from_url(AMQP_URL) as producer:
        producer.publish(topic, "queued")
    with broker_from_url(AMQP_URL) as consumer:
        assert consumer.receive(topic, timeout=2) == "queued"
