from __future__ import annotations

import io
import json
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.domain.model_connection import ModelConnection
from backend.infrastructure.settings.file_model_connection_repository import FileModelConnectionRepository
from backend.main import create_app


@pytest.fixture(autouse=True)
def reset_settings_cache():
    yield
    get_settings.cache_clear()


def build_client(monkeypatch) -> tuple[TestClient, Path]:
    data_dir = Path(".tmp") / "pytest-account-export-api" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    return TestClient(create_app()), data_dir


def register(client: TestClient, username: str) -> dict:
    response = client.post(
        "/auth/register",
        json={"username": username, "password": "password123", "display_name": username},
    )
    assert response.status_code == 200
    return response.json()["data"]


def authorization(session: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}


def test_account_export_requires_authentication(monkeypatch):
    client, _ = build_client(monkeypatch)

    response = client.get("/account/export")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_account_export_uses_authenticated_user_and_fixed_safe_download_headers(monkeypatch):
    client, data_dir = build_client(monkeypatch)
    current = register(client, "current-export-user")
    other = register(client, "other-export-user")
    current_id = current["user"]["user_id"]
    other_id = other["user"]["user_id"]
    current_root = data_dir / "users" / current_id
    other_root = data_dir / "users" / other_id
    (current_root / "meals.csv").write_text(
        "date,meal,food,amount,calories,protein,carbs,fat\n"
        "2026-07-15,dinner,豆腐,200g,160,16,8,8\n",
        encoding="utf-8",
    )
    (other_root / "meals.csv").write_text("other-user-secret", encoding="utf-8")
    (current_root / "preferences.json").write_text(
        json.dumps(
            {"language": "zh-CN", "unit_system": "metric", "timezone": "Asia/Shanghai"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    FileModelConnectionRepository(data_dir).save(
        current_id,
        ModelConnection(
            model="用户模型",
            encrypted_api_key="encrypted-secret",
            api_key_hint="********cret",
        ),
    )
    archives_before = list(data_dir.rglob("*.zip"))

    response = client.get(
        f"/account/export?user_id={other_id}",
        headers=authorization(current),
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    disposition = response.headers["content-disposition"]
    assert disposition == 'attachment; filename="account-data-export.zip"'
    assert current_id not in disposition
    assert other_id not in disposition
    assert "current-export-user" not in disposition
    with ZipFile(io.BytesIO(response.content)) as exported:
        assert exported.namelist() == [
            "identity.json",
            "model-connection.json",
            "preferences.json",
            "profile.json",
            "records/meals.csv",
            "records/workouts.csv",
        ]
        identity = json.loads(exported.read("identity.json"))
        contents = b"\n".join(exported.read(name) for name in exported.namelist())
    assert identity["user_id"] == current_id
    assert identity["username"] == "current-export-user"
    assert b"other-user-secret" not in contents
    assert b"encrypted-secret" not in contents
    assert b"api_key_hint" not in contents
    assert list(data_dir.rglob("*.zip")) == archives_before == []


def test_account_export_openapi_has_no_client_supplied_target(monkeypatch):
    client, _ = build_client(monkeypatch)

    operation = client.get("/openapi.json").json()["paths"]["/account/export"]["get"]

    assert "requestBody" not in operation
    assert {parameter["name"] for parameter in operation.get("parameters", [])} == {
        "authorization"
    }
