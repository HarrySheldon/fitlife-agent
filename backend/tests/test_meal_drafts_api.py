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
    data_dir = Path(".tmp") / "pytest-meal-drafts-api" / uuid4().hex
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


def _payload(food_id: str, *, name: str = "Lunch") -> dict:
    return {
        "log_date": "2026-07-24",
        "name": name,
        "meal_type": "lunch",
        "entry_method": "form",
        "items": [
            {
                "catalog_food_id": food_id,
                "amount": 100,
                "unit": "g",
            },
            {
                "amount": 150,
                "unit": "g",
                "custom_food": {
                    "name": "Tofu",
                    "basis_type": "per_100g",
                    "basis_amount": 100,
                    "unit": "g",
                    "calories": 80,
                    "carbs": 2,
                    "protein": 8,
                    "fat": 4,
                },
            },
        ],
    }


def test_authenticated_draft_update_conflict_and_idempotent_confirm(client):
    owner = _register(client, "meal-owner")
    other = _register(client, "meal-other")
    foods = client.get(
        "/api/v1/catalog/foods/search",
        params={"q": "dami"},
        headers=owner,
    ).json()["data"]
    rice_id = foods[0]["id"]

    created = client.post(
        "/api/v1/meal-drafts",
        headers=owner,
        json=_payload(rice_id),
    )
    assert created.status_code == 200
    draft = created.json()["data"]
    assert draft["version"] == 1
    assert draft["payload"]["items"][0]["calories"] == 365

    foreign = client.get(
        f"/api/v1/meal-drafts/{draft['id']}",
        headers=other,
    )
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "DRAFT_NOT_FOUND"
    assert foreign.json()["error"]["message"] != "DRAFT_NOT_FOUND"

    updated = client.patch(
        f"/api/v1/meal-drafts/{draft['id']}",
        headers={**owner, "If-Match": "1"},
        json=_payload(rice_id, name="Updated lunch"),
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["version"] == 2

    stale = client.patch(
        f"/api/v1/meal-drafts/{draft['id']}",
        headers={**owner, "If-Match": "1", "Accept-Language": "zh-CN"},
        json=_payload(rice_id, name="Stale"),
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "DRAFT_VERSION_CONFLICT"
    assert stale.json()["error"]["message"] == (
        "The meal draft changed. Reload it and try again."
    )

    key = str(uuid4())
    confirmed = client.post(
        f"/api/v1/meal-drafts/{draft['id']}/confirm",
        headers={
            **owner,
            "If-Match": "2",
            "Idempotency-Key": key,
        },
    )
    assert confirmed.status_code == 200
    meal = confirmed.json()["data"]
    assert len(meal["items"]) == 2

    replay = client.post(
        f"/api/v1/meal-drafts/{draft['id']}/confirm",
        headers={
            **owner,
            "If-Match": "2",
            "Idempotency-Key": key,
        },
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["id"] == meal["id"]
    assert replay.json()["data"]["replayed"] is True


def test_draft_custom_food_rejects_unsupported_alias_field(client):
    owner = _register(client, "meal-alias-contract")
    response = client.post(
        "/api/v1/meal-drafts",
        headers=owner,
        json={
            "log_date": "2026-07-24",
            "name": "Lunch",
            "meal_type": "lunch",
            "entry_method": "form",
            "items": [
                {
                    "amount": 100,
                    "unit": "g",
                    "custom_food": {
                        "name": "Rice bowl",
                        "basis_type": "per_100g",
                        "basis_amount": 100,
                        "unit": "g",
                        "calories": 150,
                        "carbs": 30,
                        "protein": 4,
                        "fat": 2,
                        "aliases": ["rice"],
                    },
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "if_match",
    ["+1", "01", '""1""', "9" * 20, "9" * 5000],
)
def test_draft_update_rejects_malformed_if_match(client, if_match):
    owner = _register(client, f"meal-etag-{uuid4().hex[:8]}")
    response = client.patch(
        "/api/v1/meal-drafts/missing",
        headers={**owner, "If-Match": if_match},
        json={
            "log_date": "2026-07-24",
            "name": "Lunch",
            "meal_type": "lunch",
            "entry_method": "form",
            "items": [],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DRAFT_VERSION_INVALID"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/v1/meal-drafts"),
        ("get", "/api/v1/meal-drafts/missing"),
        ("patch", "/api/v1/meal-drafts/missing"),
        ("delete", "/api/v1/meal-drafts/missing"),
        ("post", "/api/v1/meal-drafts/missing/confirm"),
    ],
)
def test_meal_draft_routes_require_authentication(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert response.json()["error"]["message"] != "AUTH_REQUIRED"
