from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.infrastructure.auth.file_identity_repository import FileIdentityRepository
from backend.main import create_app
from backend.tools import auth_store as auth_store_module
from backend.tools.data_access import DEFAULT_PROFILE


@pytest.fixture(autouse=True)
def reset_settings_cache():
    yield
    get_settings.cache_clear()


def build_client(monkeypatch) -> TestClient:
    data_dir = Path(".tmp") / "pytest-optional-auth-api" / uuid4().hex
    data_dir.mkdir(parents=True)
    (data_dir / "user_profile.json").write_text(
        DEFAULT_PROFILE.model_dump_json(),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    return TestClient(create_app())


def register(client: TestClient, username: str) -> dict:
    response = client.post(
        "/auth/register",
        json={"username": username, "password": "password123", "display_name": username},
    )
    assert response.status_code == 200
    return response.json()["data"]


@pytest.mark.parametrize(
    "authorization",
    ["Bearer", "Basic credentials"],
)
def test_optional_auth_rejects_malformed_authorization_header(monkeypatch, authorization: str):
    response = build_client(monkeypatch).get(
        "/profile",
        headers={"Authorization": authorization},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_TOKEN_INVALID"


def test_optional_auth_rejects_token_with_invalid_signature(monkeypatch):
    client = build_client(monkeypatch)
    token = register(client, "invalid-signature")["access_token"]
    replacement = "A" if token[-1] != "A" else "B"

    response = client.get(
        "/profile",
        headers={"Authorization": f"Bearer {token[:-1]}{replacement}"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_TOKEN_INVALID"


def test_optional_auth_rejects_expired_token(monkeypatch):
    client = build_client(monkeypatch)
    token = register(client, "expired-token")["access_token"]

    class FutureDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2100, 1, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(auth_store_module, "datetime", FutureDateTime)

    response = client.get(
        "/profile",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_TOKEN_INVALID"


def test_optional_auth_rejects_version_stale_token(monkeypatch):
    client = build_client(monkeypatch)
    session = register(client, "version-stale-token")
    FileIdentityRepository(get_settings().data_dir).rotate_token_version(
        session["user"]["user_id"]
    )

    response = client.get(
        "/profile",
        headers={"Authorization": f"Bearer {session['access_token']}"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_TOKEN_INVALID"


def test_optional_auth_preserves_legacy_anonymous_profile_without_header(monkeypatch):
    response = build_client(monkeypatch).get("/profile")

    assert response.status_code == 200
    assert response.json()["data"] == DEFAULT_PROFILE.model_dump()


def test_authenticated_legacy_profile_write_requires_narrow_personalization_route(monkeypatch):
    client = build_client(monkeypatch)
    session = register(client, "narrow-profile-writer")
    headers = {"Authorization": f"Bearer {session['access_token']}"}

    response = client.post(
        "/profile",
        headers=headers,
        json=DEFAULT_PROFILE.model_dump(),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PROFILE_VERSIONED_WRITE_REQUIRED"


def test_authenticated_personalization_updates_only_training_fields(monkeypatch):
    client = build_client(monkeypatch)
    session = register(client, "training-personalization")
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    before = client.get("/profile", headers=headers).json()["data"]

    response = client.patch(
        "/profile/personalization",
        headers=headers,
        json={
            "experience_level": "experienced",
            "training_preference": "strength",
        },
    )

    assert response.status_code == 200
    saved = response.json()["data"]
    assert saved["experience_level"] == "experienced"
    assert saved["training_preference"] == "strength"
    for field in (
        "height_cm",
        "weight_kg",
        "age",
        "goal",
        "daily_calorie_target",
        "daily_protein_target",
    ):
        assert saved[field] == before[field]
