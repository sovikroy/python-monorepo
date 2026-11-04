import threading
from datetime import UTC, datetime

from contracts import ORDER_PLACED_TOPIC, OrderPlaced
from messaging import InMemoryBroker, publish_event
from notifier_worker.worker import process_one, render, run


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


def make_event(order_id: str = "abcdef1234") -> OrderPlaced:
    return OrderPlaced(
        order_id=order_id,
        customer_email="ada@example.com",
        total_cents=4249,
        item_count=2,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_render() -> None:
    subject, body = render(make_event())
    assert subject == "Order abcdef12 confirmed"
    assert "2 item(s)" in body
    assert "$42.49" in body


def test_process_one_sends_notification() -> None:
    broker, notifier = InMemoryBroker(), RecordingNotifier()
    publish_event(broker, ORDER_PLACED_TOPIC, make_event())
    assert process_one(broker, notifier) is True
    assert notifier.sent[0][0] == "ada@example.com"
    assert process_one(broker, notifier) is False


def test_run_drains_queue_and_skips_bad_messages() -> None:
    broker, notifier = InMemoryBroker(), RecordingNotifier()
    publish_event(broker, ORDER_PLACED_TOPIC, make_event("first"))
    broker.publish(ORDER_PLACED_TOPIC, "not json")
    publish_event(broker, ORDER_PLACED_TOPIC, make_event("second"))

    stop = threading.Event()

    class StopWhenDrained(RecordingNotifier):
        def send(self, to: str, subject: str, body: str) -> None:
            notifier.send(to, subject, body)
            if len(notifier.sent) == 2:
                stop.set()

    run(broker, StopWhenDrained(), stop)
    assert [s[1] for s in notifier.sent] == ["Order first confirmed", "Order second confirmed"]
