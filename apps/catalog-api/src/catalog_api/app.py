"""HTTP routes for the catalog service."""

from fastapi import FastAPI, HTTPException

from catalog_api.repository import ProductRepository
from contracts import Product
from servicekit import ServiceSettings
from servicekit.http import create_app


class Settings(ServiceSettings):
    service_name: str = "catalog-api"


def build_app(settings: Settings | None = None, repo: ProductRepository | None = None) -> FastAPI:
    settings = settings or Settings()
    products = repo or ProductRepository()
    app = create_app(settings)

    @app.get("/products", tags=["catalog"])
    def list_products() -> list[Product]:
        return products.list()

    @app.get("/products/{sku}", tags=["catalog"])
    def get_product(sku: str) -> Product:
        product = products.get(sku)
        if product is None:
            raise HTTPException(status_code=404, detail=f"unknown product {sku!r}")
        return product

    return app
