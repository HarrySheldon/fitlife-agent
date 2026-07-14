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


def build_client(monkeypatch) -> TestClient:
    data_dir = Path(".tmp") / "pytest-preferences-api" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    return TestClient(create_app())


def register(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/auth/register",
        json={"username": username, "password": "password123", "display_name": username},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def test_preferences_routes_require_authentication(monkeypatch):
    client = build_client(monkeypatch)

    assert client.get("/settings/preferences").status_code == 401
    assert client.patch("/settings/preferences", json={"language": "zh-CN"}).status_code == 401


def test_preferences_initialize_from_headers_then_ignore_later_hints(monkeypatch):
    client = build_client(monkeypatch)
    headers = register(client, "preference-user")

    initialized = client.get(
        "/settings/preferences",
        headers={**headers, "Accept-Language": "zh-CN,zh;q=0.9", "X-Timezone": "Asia/Shanghai"},
    )
    fetched = client.get(
        "/settings/preferences",
        headers={**headers, "Accept-Language": "en-US", "X-Timezone": "America/New_York"},
    )

    assert initialized.status_code == 200
    assert initialized.json()["processing_mode"] == "deterministic"
    assert initialized.json()["data"] == {
        "language": "zh-CN",
        "unit_system": "metric",
        "timezone": "Asia/Shanghai",
    }
    assert fetched.json()["data"] == initialized.json()["data"]


def test_preferences_patch_is_partial_and_user_isolated(monkeypatch):
    client = build_client(monkeypatch)
    first = register(client, "preference-first")
    second = register(client, "preference-second")

    changed = client.patch(
        "/settings/preferences",
        headers=first,
        json={"language": "zh-CN", "unit_system": "imperial", "timezone": "Asia/Shanghai"},
    )
    partial = client.patch("/settings/preferences", headers=first, json={"timezone": "Europe/London"})
    untouched = client.get("/settings/preferences", headers={**second, "X-Timezone": "UTC"})

    assert changed.status_code == 200
    assert partial.json()["data"] == {
        "language": "zh-CN",
        "unit_system": "imperial",
        "timezone": "Europe/London",
    }
    assert untouched.json()["data"] == {
        "language": "en-US",
        "unit_system": "metric",
        "timezone": "UTC",
    }


def test_preferences_reject_invalid_values(monkeypatch):
    client = build_client(monkeypatch)
    headers = register(client, "preference-invalid")

    invalid_language = client.patch("/settings/preferences", headers=headers, json={"language": "fr-FR"})
    invalid_unit = client.patch("/settings/preferences", headers=headers, json={"unit_system": "stone"})
    invalid_timezone = client.patch("/settings/preferences", headers=headers, json={"timezone": "GMT+8"})

    assert invalid_language.status_code == 422
    assert invalid_unit.status_code == 422
    assert invalid_timezone.status_code == 422

