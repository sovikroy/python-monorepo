"""HTTP routes for the orders service."""

from fastapi import FastAPI, HTTPException

from contracts import Order, OrderCreate
from messaging import broker_from_url
from orders_api.catalog_client import HttpCatalog
from orders_api.service import OrderService, UnknownProductError
from servicekit import ServiceSettings
from servicekit.http import create_app


class Settings(ServiceSettings):
    service_name: str = "orders-api"
    catalog_url: str = "http://localhost:8001"
    # The scheme picks the transport: redis://, amqp://, tcp:// or memory:// (tests).
    broker_url: str = "memory://"


def build_app(settings: Settings | None = None, service: OrderService | None = None) -> FastAPI:
    settings = settings or Settings()
    orders = service or OrderService(
        catalog=HttpCatalog.from_url(settings.catalog_url),
        broker=broker_from_url(settings.broker_url),
    )
    app = create_app(settings)

    @app.post("/orders", status_code=201, tags=["orders"])
    def place_order(request: OrderCreate) -> Order:
        try:
            return orders.place(request)
        except UnknownProductError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/orders/{order_id}", tags=["orders"])
    def get_order(order_id: str) -> Order:
        order = orders.get(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="order not found")
        return order

    return app
