"""The consume loop, written so tests can drive it step by step."""

import logging
import threading
from typing import Protocol

from contracts import ORDER_PLACED_TOPIC, OrderPlaced
from messaging import Broker, receive_event

log = logging.getLogger(__name__)


class Notifier(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class LogNotifier:
    """Stand-in for an email/SMS provider: writes the message to the log."""

    def send(self, to: str, subject: str, body: str) -> None:
        log.info("notify to=%s subject=%r body=%r", to, subject, body)


def render(event: OrderPlaced) -> tuple[str, str]:
    subject = f"Order {event.order_id[:8]} confirmed"
    body = (
        f"Thanks for your order of {event.item_count} item(s). "
        f"Total: ${event.total_cents / 100:.2f}."
    )
    return subject, body


def process_one(broker: Broker, notifier: Notifier, timeout: float = 1.0) -> bool:
    """Handle at most one event. Returns ``True`` if an event was processed."""
    event = receive_event(broker, ORDER_PLACED_TOPIC, OrderPlaced, timeout=timeout)
    if event is None:
        return False
    subject, body = render(event)
    notifier.send(event.customer_email, subject, body)
    return True


def run(broker: Broker, notifier: Notifier, stop: threading.Event) -> None:
    """Process events until ``stop`` is set (e.g. on SIGTERM)."""
    log.info("listening on %s", ORDER_PLACED_TOPIC)
    while not stop.is_set():
        try:
            process_one(broker, notifier)
        except Exception:  # keep the worker alive; a real one would dead-letter the event
            log.exception("failed to process event")
    log.info("stopped")
