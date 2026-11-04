"""Business logic, kept free of HTTP so it is easy to test."""

import uuid
from datetime import UTC, datetime

from contracts import ORDER_PLACED_TOPIC, Order, OrderCreate, OrderPlaced, OrderStatus
from messaging import Broker, publish_event
from orders_api.catalog_client import Catalog


class UnknownProductError(Exception):
    def __init__(self, sku: str) -> None:
        super().__init__(f"unknown product {sku!r}")
        self.sku = sku


class OrderService:
    def __init__(self, catalog: Catalog, broker: Broker) -> None:
        self._catalog = catalog
        self._broker = broker
        self._orders: dict[str, Order] = {}

    def place(self, request: OrderCreate) -> Order:
        total = 0
        for item in request.items:
            product = self._catalog.get_product(item.sku)
            if product is None:
                raise UnknownProductError(item.sku)
            total += product.price_cents * item.quantity

        order = Order(
            id=uuid.uuid4().hex,
            customer_email=request.customer_email,
            items=request.items,
            total_cents=total,
            status=OrderStatus.PLACED,
            created_at=datetime.now(UTC),
        )
        self._orders[order.id] = order
        publish_event(
            self._broker,
            ORDER_PLACED_TOPIC,
            OrderPlaced(
                order_id=order.id,
                customer_email=order.customer_email,
                total_cents=order.total_cents,
                item_count=sum(i.quantity for i in order.items),
                occurred_at=order.created_at,
            ),
        )
        return order

    def get(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)
