"""Events published on the message broker."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

ORDER_PLACED_TOPIC = "orders.placed"


class OrderPlaced(BaseModel):
    """Published by orders-api after an order is stored; consumed by notifier-worker."""

    model_config = ConfigDict(frozen=True)

    order_id: str
    customer_email: str
    total_cents: int = Field(ge=0)
    item_count: int = Field(gt=0)
    occurred_at: datetime
