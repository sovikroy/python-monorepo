"""Shared data contracts: the shapes services send to each other.

Keeping these in one library means a producer and its consumers can never
drift apart silently: changing a model here re-tests every service that uses it.
"""

from contracts.catalog import Product
from contracts.events import ORDER_PLACED_TOPIC, OrderPlaced
from contracts.orders import Order, OrderCreate, OrderItem, OrderStatus

__all__ = [
    "ORDER_PLACED_TOPIC",
    "Order",
    "OrderCreate",
    "OrderItem",
    "OrderPlaced",
    "OrderStatus",
    "Product",
]
