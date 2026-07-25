from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app


@pytest.fixture(autouse=True)
def reset_settings_cache():
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch):
    data_dir = Path(".tmp") / "pytest-food-catalog-api" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client


def _register(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/auth/register",
        json={
            "username": username,
            "password": "password123",
            "display_name": username,
        },
    )
    assert response.status_code == 200
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_catalog_search_custom_food_favorite_and_owner_isolation(client):
    first = _register(client, "catalog-owner")
    second = _register(client, "catalog-other")

    seeded = client.get(
        "/api/v1/catalog/foods/search",
        params={"q": "dami"},
        headers=first,
    )
    assert seeded.status_code == 200
    rice = seeded.json()["data"][0]
    assert rice["source_name"] == "USDA FoodData Central"
    assert rice["source_record_id"] == "169756"

    custom = client.post(
        "/api/v1/catalog/foods/custom",
        headers=first,
        json={
            "name": "My oat bowl",
            "basis_type": "per_serving",
            "basis_amount": 1,
            "unit": "bowl",
            "calories": 410,
            "carbs": 62,
            "protein": 24,
            "fat": 9,
            "aliases": ["我的燕麦碗", "catalog-owner-private-oat-bowl"],
        },
    )
    assert custom.status_code == 200
    custom_food = custom.json()["data"]
    assert custom_food["source"] == "user_custom"
    assert custom_food["owner_user_id"] is not None
    assert client.get(
        "/api/v1/catalog/foods/search",
        params={"q": "catalog-owner-private-oat-bowl"},
        headers=second,
    ).json()["data"] == []

    favorite = client.put(
        f"/api/v1/catalog/foods/{rice['id']}/favorite",
        headers=first,
    )
    assert favorite.status_code == 200
    assert client.get(
        "/api/v1/catalog/foods/search",
        params={"q": "dami"},
        headers=first,
    ).json()["data"][0]["is_favorite"] is True
    assert client.delete(
        f"/api/v1/catalog/foods/{rice['id']}/favorite",
        headers=first,
    ).status_code == 200


def test_catalog_rejects_incomplete_custom_food_and_requires_auth(client):
    unauthenticated = client.get("/api/v1/catalog/foods/search")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["message"] != "AUTH_REQUIRED"
    headers = _register(client, "catalog-validation")

    response = client.post(
        "/api/v1/catalog/foods/custom",
        headers=headers,
        json={
            "name": "Incomplete",
            "basis_type": "per_100g",
            "basis_amount": 100,
            "unit": "g",
            "calories": 100,
            "carbs": 20,
            "protein": 3,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["message"] != "VALIDATION_ERROR"
