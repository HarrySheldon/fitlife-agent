from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.infrastructure.auth.file_identity_repository import FileIdentityRepository, hash_password
from backend.main import create_app
from backend.tools import auth_store as auth_store_module
from backend.tools.auth_store import authenticate_user, create_access_token, register_user, user_from_token


@pytest.fixture(autouse=True)
def reset_settings_cache():
    yield
    get_settings.cache_clear()


def test_token_is_bound_to_current_integer_identity_version(monkeypatch):
    data_dir = Path(".tmp") / "pytest-session-versioning" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    user = register_user("versioned-user", None, None, "password123", "Versioned User")

    token = create_access_token(user)
    payload = _decode_payload(token)

    assert payload["ver"] == 0
    assert type(payload["ver"]) is int
    assert user_from_token(token) == user

    FileIdentityRepository(data_dir).rotate_token_version(user.user_id)

    assert user_from_token(token) is None


def test_legacy_token_without_version_is_version_zero_until_rotation(monkeypatch):
    data_dir = Path(".tmp") / "pytest-session-versioning" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    user = register_user("legacy-session", None, None, "password123", "Legacy Session")
    payload = _decode_payload(create_access_token(user))
    payload.pop("ver")
    legacy_token = _sign_payload(payload, get_settings().auth_secret)

    assert user_from_token(legacy_token) == user

    FileIdentityRepository(data_dir).rotate_token_version(user.user_id)

    assert user_from_token(legacy_token) is None


def test_new_token_for_legacy_identity_migrates_and_carries_version_zero(monkeypatch):
    data_dir = Path(".tmp") / "pytest-session-versioning" / uuid4().hex
    data_dir.mkdir(parents=True)
    users_path = data_dir / "users.json"
    users_path.write_text(
        json.dumps(
            [
                {
                    "user_id": "legacy-identity",
                    "username": "legacy-identity",
                    "email": None,
                    "phone": None,
                    "display_name": "Legacy Identity",
                    "password_hash": hash_password("password123"),
                    "created_at": "2026-07-01T00:00:00+00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()

    user = authenticate_user("LEGACY-IDENTITY", "password123")
    assert user is not None
    token = create_access_token(user)

    assert _decode_payload(token)["ver"] == 0
    assert json.loads(users_path.read_text(encoding="utf-8"))[0]["token_version"] == 0


def test_protected_request_rejects_older_token_after_rotation(monkeypatch):
    data_dir = Path(".tmp") / "pytest-session-versioning" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    user = register_user("api-session", None, None, "password123", "API Session")
    token = create_access_token(user)
    headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(create_app())

    assert client.get("/auth/me", headers=headers).status_code == 200

    FileIdentityRepository(data_dir).rotate_token_version(user.user_id)
    rejected = client.get("/auth/me", headers=headers)

    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "AUTH_TOKEN_INVALID"


def test_signed_token_with_non_integer_version_is_rejected(monkeypatch):
    data_dir = Path(".tmp") / "pytest-session-versioning" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    user = register_user("invalid-version", None, None, "password123", "Invalid Version")
    payload = _decode_payload(create_access_token(user))
    payload["ver"] = "0"

    token = _sign_payload(payload, get_settings().auth_secret)

    assert user_from_token(token) is None


def test_token_expiring_at_current_second_is_rejected(monkeypatch):
    data_dir = Path(".tmp") / "pytest-session-versioning" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    user = register_user("expiration-boundary", None, None, "password123", "Expiration Boundary")
    current_timestamp = 1_800_000_000
    token = _sign_payload(
        {"sub": user.user_id, "exp": current_timestamp, "ver": 0},
        get_settings().auth_secret,
    )

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(current_timestamp, tz)

    monkeypatch.setattr(auth_store_module, "datetime", FrozenDateTime)

    assert user_from_token(token) is None


def _decode_payload(token: str) -> dict:
    payload_part = token.split(".", 1)[0]
    padding = "=" * (-len(payload_part) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_part + padding).decode("utf-8"))


def _sign_payload(payload: dict, secret: str) -> str:
    payload_part = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    digest = hmac.new(secret.encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256).digest()
    signature = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"{payload_part}.{signature}"
