from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from contracts import OrderCreate, OrderItem, OrderPlaced, Product


def test_product_rejects_negative_price() -> None:
    with pytest.raises(ValidationError):
        Product(sku="x", name="X", price_cents=-1)


def test_order_create_requires_items() -> None:
    with pytest.raises(ValidationError):
        OrderCreate(customer_email="ada@example.com", items=[])


def test_order_create_rejects_bad_email() -> None:
    with pytest.raises(ValidationError):
        OrderCreate(customer_email="not-an-email", items=[OrderItem(sku="x", quantity=1)])


def test_order_item_rejects_zero_quantity() -> None:
    with pytest.raises(ValidationError):
        OrderItem(sku="x", quantity=0)


def test_event_round_trips_through_json() -> None:
    event = OrderPlaced(
        order_id="o1",
        customer_email="ada@example.com",
        total_cents=1500,
        item_count=2,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert OrderPlaced.model_validate_json(event.model_dump_json()) == event
