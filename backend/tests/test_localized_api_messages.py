from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.domain.errors import ApplicationError
from backend.i18n import language_from_accept_language, translate_public_message
from backend.infrastructure.settings.file_user_preferences_repository import (
    FileUserPreferencesRepository,
)
from backend.main import create_app


@pytest.fixture(autouse=True)
def reset_settings_cache():
    yield
    get_settings.cache_clear()


def build_client(monkeypatch) -> TestClient:
    data_dir = Path(".tmp") / "pytest-localized-api" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    return TestClient(create_app())


def register(client: TestClient, language: str = "en-US") -> dict[str, str]:
    response = client.post(
        "/auth/register",
        headers={"Accept-Language": language},
        json={
            "username": f"user-{uuid4().hex[:8]}",
            "password": "password123",
            "display_name": "Test User",
        },
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


@pytest.mark.parametrize(
    ("accept_language", "expected"),
    [
        ("en-US,en;q=0.9", "Invalid account or password."),
        ("zh-CN,zh;q=0.9", "账号或密码无效。"),
    ],
)
def test_unauthenticated_auth_error_uses_accept_language(monkeypatch, accept_language, expected):
    client = build_client(monkeypatch)

    response = client.post(
        "/auth/login",
        headers={"Accept-Language": accept_language},
        json={"identifier": "missing-user", "password": "password123"},
    )

    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "AUTH_INVALID_CREDENTIALS",
        "message": expected,
    }
    assert response.json()["message"] == expected


@pytest.mark.parametrize(
    ("accept_language", "expected"),
    [
        ("en-US", "Authentication is required."),
        ("zh-CN", "需要登录后才能继续。"),
    ],
)
def test_unauthenticated_protected_error_uses_accept_language(monkeypatch, accept_language, expected):
    client = build_client(monkeypatch)

    response = client.get("/settings/preferences", headers={"Accept-Language": accept_language})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert response.json()["error"]["message"] == expected


def test_authenticated_messages_use_account_language_not_request_header(monkeypatch):
    client = build_client(monkeypatch)
    headers = register(client)
    changed = client.patch(
        "/settings/preferences",
        headers={**headers, "Accept-Language": "en-US"},
        json={"language": "zh-CN"},
    )
    assert changed.status_code == 200

    response = client.patch(
        "/settings/preferences",
        headers={**headers, "Accept-Language": "en-US"},
        json={"unit_system": "imperial"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "偏好设置已保存。"


@pytest.mark.parametrize(
    ("accept_language", "expected"),
    [
        ("en-US", "Check the submitted fields and try again."),
        ("zh-CN", "请检查提交的字段后重试。"),
    ],
)
def test_validation_error_has_stable_code_and_localized_public_message(
    monkeypatch, accept_language, expected
):
    client = build_client(monkeypatch)

    response = client.post(
        "/auth/login",
        headers={"Accept-Language": accept_language},
        json={"identifier": "x", "password": "short"},
    )

    assert response.status_code == 422
    assert response.json()["error"] == {"code": "VALIDATION_ERROR", "message": expected}


def test_fixed_agent_error_uses_authenticated_account_language(monkeypatch):
    client = build_client(monkeypatch)
    headers = register(client)
    client.patch("/settings/preferences", headers=headers, json={"language": "zh-CN"})

    response = client.post(
        "/chat",
        headers={**headers, "Accept-Language": "en-US"},
        json={"question": "Keep this question unchanged"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AI_NOT_CONFIGURED"
    assert response.json()["error"]["message"] == "请先配置并启用模型连接，再使用 Agent 功能。"


@pytest.mark.parametrize(
    ("language", "opposite_accept_language", "success_message", "invalid_message"),
    [
        ("en-US", "zh-CN", "Upload saved.", "Only CSV files are supported."),
        ("zh-CN", "en-US", "上传已保存。", "仅支持 CSV 文件。"),
    ],
)
def test_upload_messages_use_account_language_and_invalid_files_have_stable_code(
    monkeypatch,
    language,
    opposite_accept_language,
    success_message,
    invalid_message,
):
    client = build_client(monkeypatch)
    headers = register(client)
    changed = client.patch(
        "/settings/preferences",
        headers=headers,
        json={"language": language},
    )
    assert changed.status_code == 200
    localized_headers = {**headers, "Accept-Language": opposite_accept_language}

    success = client.post(
        "/upload/meals",
        headers=localized_headers,
        files={"file": ("meals.csv", b"date,name\n2026-07-14,Lunch\n", "text/csv")},
    )
    invalid = client.post(
        "/upload/workouts",
        headers=localized_headers,
        files={"file": ("workouts.txt", b"not,csv", "text/plain")},
    )

    assert success.status_code == 200
    assert success.json()["message"] == success_message
    assert success.json()["processing_mode"] == "deterministic"
    assert invalid.status_code == 422
    assert invalid.json()["message"] == invalid_message
    assert invalid.json()["processing_mode"] == "deterministic"
    assert invalid.json()["error"] == {
        "code": "INVALID_UPLOAD_FILE",
        "message": invalid_message,
    }


@pytest.mark.parametrize(
    ("accept_language", "expected_language"),
    [("zh-CN", "zh-CN"), (None, "en-US")],
)
def test_application_error_survives_preferences_read_failure(
    monkeypatch, accept_language, expected_language
):
    client = build_client(monkeypatch)
    headers = register(client)
    fallback = "Configure and enable a model connection before using Agent features."

    def fail_with_application_error():
        raise ApplicationError(
            code="AI_NOT_CONFIGURED",
            message=fallback,
            status_code=409,
            processing_mode="agent",
        )

    client.app.add_api_route("/_test/application-error", fail_with_application_error)

    def fail_preferences_read(_repository, _user_id):
        raise OSError("preferences unavailable")

    monkeypatch.setattr(FileUserPreferencesRepository, "get", fail_preferences_read)
    if accept_language is not None:
        headers["Accept-Language"] = accept_language

    response = client.get("/_test/application-error", headers=headers)
    expected = translate_public_message("AI_NOT_CONFIGURED", expected_language, fallback)

    assert response.status_code == 409
    assert response.json() == {
        "success": False,
        "data": None,
        "message": expected,
        "processing_mode": "agent",
        "error": {"code": "AI_NOT_CONFIGURED", "message": expected},
    }


@pytest.mark.parametrize(
    ("accept_language", "expected"),
    [
        ("en;q=1.1,zh;q=0.5", "zh-CN"),
        ("en;q=-0.1,zh;q=0.5", "zh-CN"),
        ("en;q=inf,zh;q=0.5", "zh-CN"),
        ("en;q=0,*;q=1", "zh-CN"),
    ],
)
def test_accept_language_rejects_invalid_q_and_honors_explicit_exclusions(
    accept_language, expected
):
    assert language_from_accept_language(accept_language) == expected
