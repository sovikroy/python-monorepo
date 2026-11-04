import pytest
from fastapi.testclient import TestClient

from catalog_api.app import build_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app())


def test_lists_seeded_products(client: TestClient) -> None:
    response = client.get("/products")
    assert response.status_code == 200
    assert [p["sku"] for p in response.json()] == ["BOOK-001", "MUG-001", "TEE-001"]


def test_gets_one_product(client: TestClient) -> None:
    response = client.get("/products/MUG-001")
    assert response.status_code == 200
    assert response.json() == {"sku": "MUG-001", "name": "Coffee mug", "price_cents": 1250}


def test_unknown_product_is_404(client: TestClient) -> None:
    assert client.get("/products/NOPE").status_code == 404


def test_health(client: TestClient) -> None:
    assert client.get("/health").json()["service"] == "catalog-api"
