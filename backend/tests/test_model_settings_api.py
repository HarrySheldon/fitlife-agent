from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app


@pytest.fixture(autouse=True)
def reset_settings_cache():
    yield
    get_settings.cache_clear()


def make_data_dir() -> Path:
    return Path(".tmp") / "pytest-model-settings-api" / uuid4().hex


def build_client(monkeypatch, *, with_cipher: bool = True, data_dir: Path | None = None) -> TestClient:
    monkeypatch.setenv("DATA_DIR", str(data_dir or make_data_dir()))
    if with_cipher:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    else:
        monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    return TestClient(create_app())


def register(client: TestClient, username: str) -> dict[str, str]:
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


def model_payload(**changes) -> dict:
    payload = {
        "provider": "openai",
        "protocol": "responses",
        "base_url": None,
        "model": "gpt-5.5",
        "enabled": True,
    }
    payload.update(changes)
    return payload


def test_model_settings_routes_require_authentication(monkeypatch):
    client = build_client(monkeypatch)

    assert client.get("/settings/model").status_code == 401
    assert client.put("/settings/model", json=model_payload()).status_code == 401
    assert client.delete("/settings/model/api-key").status_code == 401


def test_save_fetch_retain_and_clear_key_without_provider_request(monkeypatch):
    client = build_client(monkeypatch)
    headers = register(client, "model-user")

    monkeypatch.setattr(
        "backend.infrastructure.model_gateway.openai_responses.build_model_gateway",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("saving settings must not construct a provider gateway")
        ),
    )
    saved = client.put(
        "/settings/model",
        headers=headers,
        json=model_payload(api_key="sk-user-secret"),
    )
    retained = client.put(
        "/settings/model",
        headers=headers,
        json=model_payload(enabled=False),
    )
    fetched = client.get("/settings/model", headers=headers)
    cleared = client.delete("/settings/model/api-key", headers=headers)

    assert saved.status_code == 200
    assert saved.json()["processing_mode"] == "deterministic"
    assert saved.json()["data"]["api_key_configured"] is True
    assert saved.json()["data"]["api_key_hint"] == "********cret"
    assert "sk-user-secret" not in saved.text
    assert "encrypted_api_key" not in saved.text
    assert retained.json()["data"]["api_key_configured"] is True
    assert fetched.json()["data"]["enabled"] is False
    assert cleared.json()["data"]["api_key_configured"] is False


def test_connections_are_isolated_between_authenticated_users(monkeypatch):
    client = build_client(monkeypatch)
    first_headers = register(client, "first-user")
    second_headers = register(client, "second-user")

    client.put(
        "/settings/model",
        headers=first_headers,
        json=model_payload(api_key="sk-first-user"),
    )

    first = client.get("/settings/model", headers=first_headers)
    second = client.get("/settings/model", headers=second_headers)

    assert first.json()["data"]["api_key_configured"] is True
    assert second.json()["data"]["api_key_configured"] is False


def test_missing_cipher_rejects_only_new_key_writes(monkeypatch):
    client = build_client(monkeypatch, with_cipher=False)
    headers = register(client, "no-cipher-user")

    metadata_only = client.put("/settings/model", headers=headers, json=model_payload(enabled=False))
    with_key = client.put(
        "/settings/model",
        headers=headers,
        json=model_payload(api_key="sk-user-secret"),
    )

    assert metadata_only.status_code == 200
    assert with_key.status_code == 503
    assert with_key.json()["error"]["code"] == "CREDENTIAL_STORE_UNAVAILABLE"
    assert "sk-user-secret" not in with_key.text


def test_model_list_and_connection_test_require_explicit_requests(monkeypatch):
    client = build_client(monkeypatch)
    headers = register(client, "operations-user")
    calls: list[str] = []

    class FakeGateway:
        model = "gpt-5.5"

        def list_models(self):
            calls.append("list")
            return ["gpt-5.5", "gpt-5-mini"]

        def probe_tool_call(self):
            calls.append("test")

    monkeypatch.setattr(
        "backend.api.settings.create_model_gateway",
        lambda connection, api_key: FakeGateway(),
    )
    saved = client.put(
        "/settings/model",
        headers=headers,
        json=model_payload(api_key="sk-user-secret"),
    )

    assert saved.status_code == 200
    assert calls == []

    listed = client.post("/settings/model/models", headers=headers)
    tested = client.post("/settings/model/test", headers=headers)

    assert listed.status_code == 200
    assert listed.json()["data"]["models"] == ["gpt-5.5", "gpt-5-mini"]
    assert tested.status_code == 200
    assert tested.json()["data"]["status"] == "success"
    assert calls == ["list", "test"]


def test_disabled_agent_and_missing_cipher_flows_use_stable_api_errors(monkeypatch):
    data_dir = make_data_dir()
    configured_client = build_client(monkeypatch, data_dir=data_dir)
    headers = register(configured_client, "agent-settings-user")
    saved = configured_client.put(
        "/settings/model",
        headers=headers,
        json=model_payload(api_key="sk-user-secret", enabled=False),
    )

    disabled = configured_client.post(
        "/chat",
        headers=headers,
        json={"question": "Explain today's progress"},
    )

    assert saved.status_code == 200
    assert disabled.status_code == 409
    assert disabled.json()["error"]["code"] == "AI_DISABLED"

    configured_client.put(
        "/settings/model",
        headers=headers,
        json=model_payload(enabled=True),
    )
    no_cipher_client = build_client(monkeypatch, with_cipher=False, data_dir=data_dir)
    unavailable = no_cipher_client.post(
        "/chat",
        headers=headers,
        json={"question": "Explain today's progress"},
    )

    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "CREDENTIAL_STORE_UNAVAILABLE"
