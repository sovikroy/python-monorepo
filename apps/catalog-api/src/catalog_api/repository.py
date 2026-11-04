"""Product storage. In-memory for the example; swap for a database in real life."""

from collections.abc import Iterable

from contracts import Product

SEED_PRODUCTS = (
    Product(sku="BOOK-001", name="The Pragmatic Monorepo", price_cents=2999),
    Product(sku="MUG-001", name="Coffee mug", price_cents=1250),
    Product(sku="TEE-001", name="T-shirt", price_cents=1999),
)


class ProductRepository:
    def __init__(self, products: Iterable[Product] = SEED_PRODUCTS) -> None:
        self._products = {p.sku: p for p in products}

    def list(self) -> list[Product]:
        return sorted(self._products.values(), key=lambda p: p.sku)

    def get(self, sku: str) -> Product | None:
        return self._products.get(sku)
