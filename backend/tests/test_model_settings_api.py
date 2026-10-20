"""Compatibility routes must obey the same draft and activation rules."""
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.domain.model_connection import ModelConnection
from backend.domain.model_endpoint_policy import ModelEndpointPolicy
from backend.infrastructure.settings.fernet_cipher import FernetCredentialCipher
from backend.infrastructure.settings.file_model_connection_repository import FileModelConnectionRepository
from backend.main import create_app
from backend.tools.auth_store import user_from_token


@pytest.fixture(autouse=True)
def reset_settings_cache():
    yield
    get_settings.cache_clear()


def make_data_dir() -> Path:
    return Path(".tmp") / "pytest-model-settings-api" / uuid4().hex


def build_client(monkeypatch, *, with_cipher=True, data_dir=None):
    root = data_dir or make_data_dir()
    monkeypatch.setenv("DATA_DIR", str(root))
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(root / "fitlife.sqlite3"))
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", Fernet.generate_key().decode() if with_cipher else "")
    policy = ModelEndpointPolicy(resolver=lambda *_a, **_kw: [(None, None, None, None, ("8.8.8.8", 443))])
    monkeypatch.setattr("backend.api.settings._endpoint_policy", lambda: policy)
    get_settings.cache_clear()
    return TestClient(create_app())


def register(client, username):
    result = client.post("/auth/register", json={"username": username, "password": "password123", "display_name": username})
    assert result.status_code == 200
    return {"Authorization": "Bearer " + result.json()["data"]["access_token"]}


def model_payload(**changes):
    return {"provider": "openai", "protocol": "responses", "base_url": None,
        "model": "synthetic-model", "enabled": False, "expected_revision": 0, **changes}


def seed_legacy(headers, *, enabled=True):
    """Represent an existing account config, not a public activation bypass."""
    user = user_from_token(headers["Authorization"].split()[1])
    settings = get_settings()
    cipher = FernetCredentialCipher(settings.settings_encryption_key)
    repo = FileModelConnectionRepository(settings.data_dir)
    repo.save(user.user_id, ModelConnection(model="synthetic-model", enabled=enabled,
        encrypted_api_key=cipher.encrypt("synthetic-key"), api_key_hint="********-key"))
    return repo, user.user_id


def test_model_settings_routes_require_authentication(monkeypatch):
    client = build_client(monkeypatch)
    assert client.get("/settings/model").status_code == 401
    assert client.put("/settings/model", json=model_payload()).status_code == 401
    assert client.delete("/settings/model/api-key").status_code == 401


def test_save_fetch_retain_and_clear_draft_without_provider_request(monkeypatch):
    client = build_client(monkeypatch)
    headers = register(client, "model-user")
    def forbidden(*_a, **_kw):
        raise AssertionError("Saving must never construct a provider gateway")
    monkeypatch.setattr("backend.api.settings.create_model_gateway", forbidden)
    saved = client.put("/settings/model", headers=headers, json=model_payload(api_key="synthetic-secret"))
    assert saved.status_code == 200
    assert saved.json()["processing_mode"] == "deterministic"
    assert saved.json()["data"]["api_key_configured"]
    assert saved.json()["data"]["api_key_hint"] == "********cret"
    assert "synthetic-secret" not in saved.text
    assert "encrypted_api_key" not in saved.text
    retained = client.put("/settings/model", headers=headers, json=model_payload(expected_revision=1))
    assert retained.status_code == 200
    assert retained.json()["data"]["api_key_configured"]
    assert not client.get("/settings/model", headers=headers).json()["data"]["api_key_configured"]
    cleared = client.delete("/settings/model/api-key?slot=draft&expected_revision=2", headers=headers)
    assert cleared.status_code == 200
    assert not cleared.json()["data"]["draft"]["api_key_configured"]


def test_connections_are_isolated_between_authenticated_users(monkeypatch):
    client = build_client(monkeypatch)
    first = register(client, "first-user")
    second = register(client, "second-user")
    saved = client.put("/settings/model", headers=first, json=model_payload(api_key="synthetic-first"))
    assert saved.status_code == 200
    assert client.get("/settings/model/workspace", headers=first).json()["data"]["draft"]["api_key_configured"]
    assert client.get("/settings/model/workspace", headers=second).json()["data"]["draft"] is None


def test_missing_cipher_rejects_new_credential_without_exposure(monkeypatch):
    client = build_client(monkeypatch, with_cipher=False)
    headers = register(client, "no-cipher-user")
    result = client.put("/settings/model", headers=headers, json=model_payload(api_key="synthetic-secret"))
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "CREDENTIAL_STORE_UNAVAILABLE"
    assert "synthetic-secret" not in result.text


def test_model_list_and_connection_test_require_explicit_requests(monkeypatch):
    client = build_client(monkeypatch)
    headers = register(client, "operations-user")
    repo, user_id = seed_legacy(headers)
    before = repo.get_workspace(user_id).model_dump_json()
    calls = []
    class FakeGateway:
        def list_models(self):
            calls.append("list")
            return ["synthetic-model"]
        def probe_generation(self):
            calls.append("generation")
        def probe_structured(self):
            calls.append("structured")
        def close(self):
            calls.append("close")
    monkeypatch.setattr("backend.api.settings.create_model_gateway", lambda *_a: FakeGateway())
    assert client.get("/settings/model", headers=headers).status_code == 200
    assert calls == []
    listed = client.post("/settings/model/models", headers=headers)
    tested = client.post("/settings/model/test", headers=headers)
    assert listed.json()["data"]["models"] == ["synthetic-model"]
    assert tested.json()["data"]["status"] == "success"
    assert calls == ["list", "close", "generation", "structured", "close"]
    assert repo.get_workspace(user_id).model_dump_json() == before


def test_disabled_agent_and_missing_cipher_use_stable_errors(monkeypatch):
    root = make_data_dir()
    client = build_client(monkeypatch, data_dir=root)
    headers = register(client, "agent-settings-user")
    repo, user_id = seed_legacy(headers, enabled=False)
    disabled = client.post("/chat", headers=headers, json={"question": "Explain today's progress"})
    assert disabled.status_code == 409
    assert disabled.json()["error"]["code"] == "AI_DISABLED"
    repo.save(user_id, repo.get(user_id).model_copy(update={"enabled": True}))
    no_cipher = build_client(monkeypatch, with_cipher=False, data_dir=root)
    unavailable = no_cipher.post("/chat", headers=headers, json={"question": "Explain today's progress"})
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "CREDENTIAL_STORE_UNAVAILABLE"
