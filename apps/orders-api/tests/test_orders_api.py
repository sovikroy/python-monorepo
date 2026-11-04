import httpx
import pytest
from fastapi.testclient import TestClient

from contracts import ORDER_PLACED_TOPIC, OrderPlaced, Product
from messaging import InMemoryBroker, receive_event
from orders_api.app import build_app
from orders_api.catalog_client import HttpCatalog
from orders_api.service import OrderService


class FakeCatalog:
    def __init__(self, *products: Product) -> None:
        self._products = {p.sku: p for p in products}

    def get_product(self, sku: str) -> Product | None:
        return self._products.get(sku)


@pytest.fixture
def broker() -> InMemoryBroker:
    return InMemoryBroker()


@pytest.fixture
def client(broker: InMemoryBroker) -> TestClient:
    catalog = FakeCatalog(
        Product(sku="A", name="Apple", price_cents=100),
        Product(sku="B", name="Banana", price_cents=250),
    )
    return TestClient(build_app(service=OrderService(catalog, broker)))


def test_place_order_prices_items_and_publishes_event(
    client: TestClient, broker: InMemoryBroker
) -> None:
    body = {
        "customer_email": "ada@example.com",
        "items": [{"sku": "A", "quantity": 3}, {"sku": "B", "quantity": 2}],
    }
    response = client.post("/orders", json=body)
    assert response.status_code == 201
    order = response.json()
    assert order["total_cents"] == 3 * 100 + 2 * 250
    assert order["status"] == "placed"

    event = receive_event(broker, ORDER_PLACED_TOPIC, OrderPlaced)
    assert event is not None
    assert event.order_id == order["id"]
    assert event.item_count == 5

    assert client.get(f"/orders/{order['id']}").json() == order


def test_unknown_product_is_rejected(client: TestClient, broker: InMemoryBroker) -> None:
    body = {"customer_email": "ada@example.com", "items": [{"sku": "NOPE", "quantity": 1}]}
    response = client.post("/orders", json=body)
    assert response.status_code == 422
    assert broker.pending(ORDER_PLACED_TOPIC) == 0


def test_invalid_body_is_rejected(client: TestClient) -> None:
    assert client.post("/orders", json={"customer_email": "x", "items": []}).status_code == 422


def test_missing_order_is_404(client: TestClient) -> None:
    assert client.get("/orders/does-not-exist").status_code == 404


def test_http_catalog_parses_responses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/products/A":
            return httpx.Response(200, json={"sku": "A", "name": "Apple", "price_cents": 100})
        return httpx.Response(404, json={"detail": "unknown"})

    catalog = HttpCatalog(
        httpx.Client(base_url="http://catalog", transport=httpx.MockTransport(handler))
    )
    assert catalog.get_product("A") == Product(sku="A", name="Apple", price_cents=100)
    assert catalog.get_product("Z") is None
