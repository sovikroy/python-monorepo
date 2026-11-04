"""Catalog models."""

from pydantic import BaseModel, ConfigDict, Field


class Product(BaseModel):
    """A product that can be ordered. Prices are integer cents to avoid float rounding."""

    model_config = ConfigDict(frozen=True)

    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1)
    price_cents: int = Field(ge=0)
