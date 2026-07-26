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
    data_dir = Path(".tmp") / "pytest-smart-entry-api" / uuid4().hex
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
    return {
        "Authorization": (
            f"Bearer {response.json()['data']['access_token']}"
        )
    }


def _profile(client: TestClient, headers: dict[str, str]) -> None:
    response = client.put(
        "/api/v1/profile",
        headers=headers,
        json={
            "age": 30,
            "height_cm": 175,
            "weight_kg": 70,
            "energy_parameter": "neutral",
            "activity_level": "moderate",
            "auto_target_disabled": False,
            "safety_conditions": [],
            "effective_from": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 200


def test_authenticated_smart_entry_contract_conflict_and_confirm(client):
    owner = _register(client, "smart-owner")
    other = _register(client, "smart-other")
    _profile(client, owner)
    endpoint = "/api/v1/smart-entry-drafts"
    payload = {
        "log_date": "2026-07-26",
        "raw_text": "早餐：dami 100g\n力量：squat 3x8 60kg",
    }

    assert client.post(endpoint, json=payload).status_code == 401
    created = client.post(endpoint, headers=owner, json=payload)
    assert created.status_code == 200
    assert created.json()["processing_mode"] == "deterministic"
    draft = created.json()["data"]
    assert draft["version"] == 1
    assert [item["kind"] for item in draft["payload"]["candidates"]] == [
        "food",
        "strength",
    ]
    assert all(
        item["selected_catalog_id"]
        for item in draft["payload"]["candidates"]
    )

    latest = client.get(
        endpoint,
        params={"date": "2026-07-26"},
        headers=owner,
    )
    assert latest.json()["data"]["id"] == draft["id"]
    foreign = client.get(f"{endpoint}/{draft['id']}", headers=other)
    assert foreign.status_code == 404

    conflict = client.patch(
        f"{endpoint}/{draft['id']}",
        headers={**owner, "If-Match": "2"},
        json=draft["payload"],
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "DRAFT_VERSION_CONFLICT"

    confirmed = client.post(
        f"{endpoint}/{draft['id']}/confirm",
        headers={
            **owner,
            "If-Match": "1",
            "Idempotency-Key": str(uuid4()),
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["processing_mode"] == "deterministic"
    assert len(confirmed.json()["data"]["meal_ids"]) == 1
    assert confirmed.json()["data"]["training_session_id"] is not None

    today = client.get(
        "/today",
        params={"date": "2026-07-26"},
        headers=owner,
    )
    assert today.status_code == 200
    assert today.json()["data"]["consumed"]["calories"] == 365
    assert len(today.json()["data"]["workouts"]) == 1


def test_analyze_without_model_preserves_draft_and_reports_agent_mode(client):
    headers = _register(client, "smart-agent")
    endpoint = "/api/v1/smart-entry-drafts"
    created = client.post(
        endpoint,
        headers=headers,
        json={
            "log_date": "2026-07-26",
            "raw_text": "早餐：unknown-food 1份",
        },
    ).json()["data"]

    analyzed = client.post(
        f"{endpoint}/{created['id']}/analyze",
        headers={**headers, "If-Match": "1"},
    )

    assert analyzed.status_code == 409
    assert analyzed.json()["processing_mode"] == "agent"
    assert analyzed.json()["error"]["code"] == "AI_NOT_CONFIGURED"
    preserved = client.get(
        f"{endpoint}/{created['id']}",
        headers=headers,
    )
    assert preserved.status_code == 200
    assert preserved.json()["data"]["agent_status"] == "failed"


def test_openapi_exposes_all_smart_entry_routes(client):
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]

    assert "/api/v1/smart-entry-drafts" in paths
    assert "/api/v1/smart-entry-drafts/{draft_id}" in paths
    assert "/api/v1/smart-entry-drafts/{draft_id}/analyze" in paths
    assert "/api/v1/smart-entry-drafts/{draft_id}/confirm" in paths
