"""Order models."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class OrderStatus(StrEnum):
    PLACED = "placed"
    CANCELLED = "cancelled"


class OrderItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(gt=0, le=1000)


class OrderCreate(BaseModel):
    """Request body for creating an order."""

    customer_email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    items: list[OrderItem] = Field(min_length=1)


class Order(BaseModel):
    """An order as stored and returned by the orders service."""

    id: str
    customer_email: str
    items: list[OrderItem]
    total_cents: int = Field(ge=0)
    status: OrderStatus
    created_at: datetime
