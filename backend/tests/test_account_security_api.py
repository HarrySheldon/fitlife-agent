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
    data_dir = Path(".tmp") / "pytest-account-security-api" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    return TestClient(create_app())


def register(client: TestClient, username: str, password: str = "password123") -> dict:
    response = client.post(
        "/auth/register",
        json={"username": username, "password": password, "display_name": username},
    )
    assert response.status_code == 200
    return response.json()["data"]


def authorization(session: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}


def test_password_change_returns_replacement_session_and_invalidates_old_credentials(monkeypatch):
    client = build_client(monkeypatch)
    original = register(client, "password-api-user")

    response = client.post(
        "/account/password/change",
        headers=authorization(original),
        json={"current_password": "password123", "new_password": "replacement123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["message"] == "Password changed."
    assert body["data"]["token_type"] == "bearer"
    assert body["data"]["user"] == original["user"]
    assert client.get("/auth/me", headers=authorization(original)).status_code == 401
    assert client.get("/auth/me", headers=authorization(body["data"])).status_code == 200
    assert client.post(
        "/auth/login",
        json={"identifier": "password-api-user", "password": "password123"},
    ).status_code == 401
    assert client.post(
        "/auth/login",
        json={"identifier": "password-api-user", "password": "replacement123"},
    ).status_code == 200


def test_revoke_other_sessions_has_no_body_and_returns_replacement_session(monkeypatch):
    client = build_client(monkeypatch)
    original = register(client, "revoke-api-user")

    response = client.post(
        "/account/sessions/revoke-others",
        headers=authorization(original),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["message"] == "Other sessions revoked."
    assert body["data"]["user"] == original["user"]
    assert client.get("/auth/me", headers=authorization(original)).status_code == 401
    assert client.get("/auth/me", headers=authorization(body["data"])).status_code == 200
    assert client.post(
        "/auth/login",
        json={"identifier": "revoke-api-user", "password": "password123"},
    ).status_code == 200


def test_wrong_current_password_is_localized_and_does_not_rotate_session(monkeypatch):
    client = build_client(monkeypatch)
    original = register(client, "wrong-password-user")
    headers = authorization(original)
    assert client.patch(
        "/settings/preferences",
        headers=headers,
        json={"language": "zh-CN"},
    ).status_code == 200

    response = client.post(
        "/account/password/change",
        headers={**headers, "Accept-Language": "en-US"},
        json={"current_password": "wrong-password", "new_password": "replacement123"},
    )

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "ACCOUNT_CURRENT_PASSWORD_INVALID",
        "message": "当前密码不正确。",
    }
    assert client.get("/auth/me", headers=headers).status_code == 200
    assert client.post(
        "/auth/login",
        json={"identifier": "wrong-password-user", "password": "password123"},
    ).status_code == 200


def test_same_password_has_clear_localized_error_without_rotating_session(monkeypatch):
    client = build_client(monkeypatch)
    original = register(client, "same-password-user")
    headers = authorization(original)
    client.patch("/settings/preferences", headers=headers, json={"language": "zh-CN"})

    response = client.post(
        "/account/password/change",
        headers={**headers, "Accept-Language": "en-US"},
        json={"current_password": "password123", "new_password": "password123"},
    )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "ACCOUNT_PASSWORD_UNCHANGED",
        "message": "新密码必须与当前密码不同。",
    }
    assert client.get("/auth/me", headers=headers).status_code == 200


@pytest.mark.parametrize("new_password", ["short7", "x" * 129])
def test_password_policy_validation_does_not_rotate_session(monkeypatch, new_password: str):
    client = build_client(monkeypatch)
    original = register(client, f"policy-api-{len(new_password)}")

    response = client.post(
        "/account/password/change",
        headers=authorization(original),
        json={"current_password": "password123", "new_password": new_password},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get("/auth/me", headers=authorization(original)).status_code == 200


@pytest.mark.parametrize(
    "path",
    ["/account/password/change", "/account/sessions/revoke-others"],
)
def test_account_security_routes_require_authentication(monkeypatch, path: str):
    client = build_client(monkeypatch)
    response = client.post(
        path,
        json={"current_password": "password123", "new_password": "replacement123"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_route_schemas_are_independent_and_expose_no_client_supplied_user_id(monkeypatch):
    client = build_client(monkeypatch)
    openapi = client.get("/openapi.json").json()
    change_operation = openapi["paths"]["/account/password/change"]["post"]
    revoke_operation = openapi["paths"]["/account/sessions/revoke-others"]["post"]
    schema_ref = change_operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    change_schema = openapi["components"]["schemas"][schema_ref.rsplit("/", 1)[-1]]

    assert set(change_schema["properties"]) == {"current_password", "new_password"}
    assert change_schema["additionalProperties"] is False
    assert "requestBody" not in revoke_operation


def test_client_supplied_user_id_cannot_target_another_account(monkeypatch):
    client = build_client(monkeypatch)
    current = register(client, "current-account")
    other = register(client, "other-account", "password456")

    rejected_change = client.post(
        "/account/password/change",
        headers=authorization(current),
        json={
            "user_id": other["user"]["user_id"],
            "current_password": "password123",
            "new_password": "replacement123",
        },
    )
    revoked_current = client.post(
        "/account/sessions/revoke-others",
        headers=authorization(current),
        json={"user_id": other["user"]["user_id"], "current_password": "password456"},
    )

    assert rejected_change.status_code == 422
    assert revoked_current.status_code == 200
    assert revoked_current.json()["data"]["user"] == current["user"]
    assert client.get("/auth/me", headers=authorization(other)).status_code == 200
    assert client.post(
        "/auth/login",
        json={"identifier": "other-account", "password": "password456"},
    ).status_code == 200


@pytest.mark.parametrize(
    ("path", "payload", "expected"),
    [
        (
            "/account/password/change",
            {"current_password": "password123", "new_password": "replacement123"},
            "密码已更新。",
        ),
        ("/account/sessions/revoke-others", None, "其他会话已撤销。"),
    ],
)
def test_success_messages_use_authenticated_account_language(
    monkeypatch,
    path: str,
    payload: dict | None,
    expected: str,
):
    client = build_client(monkeypatch)
    original = register(client, f"localized-{uuid4().hex[:8]}")
    headers = authorization(original)
    client.patch("/settings/preferences", headers=headers, json={"language": "zh-CN"})

    response = client.post(
        path,
        headers={**headers, "Accept-Language": "en-US"},
        json=payload,
    )

    assert response.status_code == 200
    assert response.json()["message"] == expected
