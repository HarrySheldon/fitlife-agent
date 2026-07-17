from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.infrastructure.auth.file_identity_repository import FileIdentityRepository
from backend.main import create_app
from backend.tools.data_access import DEFAULT_PROFILE


@pytest.fixture(autouse=True)
def reset_settings_cache():
    yield
    get_settings.cache_clear()


def build_client(monkeypatch) -> tuple[TestClient, Path]:
    data_dir = Path(".tmp") / "pytest-account-delete-api" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    return TestClient(create_app()), data_dir


def register(client: TestClient, username: str, password: str = "password123") -> dict:
    response = client.post(
        "/auth/register",
        json={"username": username, "password": password, "display_name": username},
    )
    assert response.status_code == 200
    return response.json()["data"]


def authorization(session: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}


def test_confirmed_account_deletion_invalidates_identity_and_existing_token(monkeypatch):
    client, _ = build_client(monkeypatch)
    session = register(client, "delete-api-user")

    response = client.request(
        "DELETE",
        "/account",
        headers=authorization(session),
        json={"password": "password123", "confirmation": "DELETE"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": None,
        "message": "Account deleted.",
    }
    assert client.get("/auth/me", headers=authorization(session)).status_code == 401
    assert client.post(
        "/auth/login",
        json={"identifier": "delete-api-user", "password": "password123"},
    ).status_code == 401


def test_deleted_account_token_cannot_mutate_anonymous_profile(monkeypatch):
    client, data_dir = build_client(monkeypatch)
    session = register(client, "deleted-profile-writer")
    headers = authorization(session)
    anonymous_profile = data_dir / "user_profile.json"
    anonymous_profile.write_text(DEFAULT_PROFILE.model_dump_json(), encoding="utf-8")
    original_profile = anonymous_profile.read_bytes()
    replacement_profile = DEFAULT_PROFILE.model_copy(update={"weight_kg": 99}).model_dump()

    assert client.request(
        "DELETE",
        "/account",
        headers=headers,
        json={"password": "password123", "confirmation": "DELETE"},
    ).status_code == 200

    response = client.post("/profile", headers=headers, json=replacement_profile)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_TOKEN_INVALID"
    assert anonymous_profile.read_bytes() == original_profile


def test_deleted_account_token_cannot_replace_anonymous_meals_upload(monkeypatch):
    client, data_dir = build_client(monkeypatch)
    session = register(client, "deleted-meals-uploader")
    headers = authorization(session)
    anonymous_meals = data_dir / "meals.csv"
    original_meals = b"date,meal\n2026-07-01,anonymous baseline\n"
    anonymous_meals.write_bytes(original_meals)

    assert client.request(
        "DELETE",
        "/account",
        headers=headers,
        json={"password": "password123", "confirmation": "DELETE"},
    ).status_code == 200

    response = client.post(
        "/upload/meals",
        headers=headers,
        files={"file": ("meals.csv", b"date,meal\n2026-07-02,attacker\n", "text/csv")},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_TOKEN_INVALID"
    assert anonymous_meals.read_bytes() == original_meals


def test_account_deletion_success_uses_language_selected_before_cleanup(monkeypatch):
    client, _ = build_client(monkeypatch)
    session = register(client, "localized-delete-user")
    headers = authorization(session)
    assert client.patch(
        "/settings/preferences",
        headers=headers,
        json={"language": "zh-CN"},
    ).status_code == 200

    response = client.request(
        "DELETE",
        "/account",
        headers={**headers, "Accept-Language": "en-US"},
        json={"password": "password123", "confirmation": "DELETE"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "账户已删除。"


def test_identity_failure_is_localized_and_can_retry_after_storage_is_missing(monkeypatch):
    client, data_dir = build_client(monkeypatch)
    session = register(client, "retry-delete-user")
    headers = authorization(session)
    user_id = session["user"]["user_id"]
    user_root = data_dir / "users" / user_id
    assert client.patch(
        "/settings/preferences",
        headers=headers,
        json={"language": "zh-CN"},
    ).status_code == 200

    def fail_identity_write(_repository, _source: Path, _destination: Path) -> None:
        raise OSError("private identity write detail")

    with monkeypatch.context() as deletion_patch:
        deletion_patch.setattr(FileIdentityRepository, "replace_file", fail_identity_write)
        failed = client.request(
            "DELETE",
            "/account",
            headers={**headers, "Accept-Language": "en-US"},
            json={"password": "password123", "confirmation": "DELETE"},
        )

    assert failed.status_code == 500
    assert failed.json()["error"] == {
        "code": "ACCOUNT_DELETE_FAILED",
        "message": "无法删除账户，请重试。",
    }
    assert "identity" not in failed.text
    assert not user_root.exists()
    assert client.get("/auth/me", headers=headers).status_code == 200

    retried = client.request(
        "DELETE",
        "/account",
        headers=headers,
        json={"password": "password123", "confirmation": "DELETE"},
    )

    assert retried.status_code == 200
    assert client.get("/auth/me", headers=headers).status_code == 401


@pytest.mark.parametrize("extra_field", ["user_id", "extra"])
def test_delete_request_forbids_client_target_and_extra_fields(monkeypatch, extra_field: str):
    client, data_dir = build_client(monkeypatch)
    current = register(client, f"strict-delete-{extra_field}")
    other = register(client, f"strict-delete-other-{extra_field}", "password456")
    current_root = data_dir / "users" / current["user"]["user_id"]
    current_root.mkdir(parents=True, exist_ok=True)
    marker = current_root / "record.json"
    marker.write_text("untouched", encoding="utf-8")
    payload = {"password": "password123", "confirmation": "DELETE"}
    payload[extra_field] = other["user"]["user_id"]

    response = client.request(
        "DELETE",
        "/account",
        headers=authorization(current),
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert marker.read_text(encoding="utf-8") == "untouched"
    assert client.get("/auth/me", headers=authorization(current)).status_code == 200
    assert client.get("/auth/me", headers=authorization(other)).status_code == 200


def test_delete_openapi_body_contains_only_password_and_confirmation(monkeypatch):
    client, _ = build_client(monkeypatch)
    openapi = client.get("/openapi.json").json()
    operation = openapi["paths"]["/account"]["delete"]
    schema_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    schema = openapi["components"]["schemas"][schema_ref.rsplit("/", 1)[-1]]

    assert set(schema["properties"]) == {"password", "confirmation"}
    assert schema["required"] == ["password", "confirmation"]
    assert schema["additionalProperties"] is False


def test_confirmed_delete_removes_all_owned_files_and_preserves_other_account(monkeypatch):
    client, data_dir = build_client(monkeypatch)
    current = register(client, "owned-delete-user")
    other = register(client, "preserved-delete-user", "password456")
    current_root = data_dir / "users" / current["user"]["user_id"]
    other_root = data_dir / "users" / other["user"]["user_id"]
    account_files = {
        "user_profile.json": "{}",
        "preferences.json": (
            '{"language":"en-US","unit_system":"metric","timezone":"UTC"}'
        ),
        "model_connection.json": "{}",
        "meals.csv": "date,meal\n",
        "workouts.csv": "date,type\n",
    }
    for filename, contents in account_files.items():
        (current_root / filename).write_text(contents, encoding="utf-8")
        (other_root / filename).write_text(f"other:{filename}", encoding="utf-8")

    response = client.request(
        "DELETE",
        "/account",
        headers=authorization(current),
        json={"password": "password123", "confirmation": "DELETE"},
    )

    assert response.status_code == 200
    assert not current_root.exists()
    assert {
        path.name: path.read_text(encoding="utf-8") for path in other_root.iterdir()
    } == {filename: f"other:{filename}" for filename in account_files}
    assert client.get("/auth/me", headers=authorization(other)).status_code == 200
    assert client.post(
        "/auth/login",
        json={"identifier": "preserved-delete-user", "password": "password456"},
    ).status_code == 200
