"""Client for catalog-api. Services talk over HTTP, never by importing each other."""

from typing import Protocol

import httpx

from contracts import Product


class Catalog(Protocol):
    def get_product(self, sku: str) -> Product | None: ...


class HttpCatalog:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    @classmethod
    def from_url(cls, base_url: str, timeout: float = 5.0) -> "HttpCatalog":
        return cls(httpx.Client(base_url=base_url, timeout=timeout))

    def get_product(self, sku: str) -> Product | None:
        response = self._client.get(f"/products/{sku}")
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        response.raise_for_status()
        return Product.model_validate_json(response.content)
