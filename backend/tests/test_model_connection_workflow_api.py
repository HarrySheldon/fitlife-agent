"""Public workflow tests: all credentials, responses and DNS are synthetic."""
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.domain.model_endpoint_policy import ModelEndpointPolicy
from backend.main import create_app


@pytest.fixture
def workflow_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(tmp_path / "fitlife.sqlite3"))
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("LLM_ENABLED", "false")
    get_settings.cache_clear()
    policy = ModelEndpointPolicy(resolver=lambda *_args, **_kwargs: [(None, None, None, None, ("8.8.8.8", 443))])
    monkeypatch.setattr("backend.api.settings._endpoint_policy", lambda: policy)
    calls = []
    class Gateway:
        def list_models(self):
            calls.append("list")
            return ["synthetic-model"]
        def probe_generation(self):
            calls.append("generation")
        def probe_structured(self):
            calls.append("structured")
        def close(self):
            calls.append("close")
    monkeypatch.setattr("backend.api.settings.create_model_gateway", lambda *_args: Gateway())
    client = TestClient(create_app())
    registered = client.post("/auth/register", json={"username": "model-workflow", "password": "password123", "display_name": "Synthetic"})
    assert registered.status_code == 200, registered.text
    headers = {"Authorization": "Bearer " + registered.json()["data"]["access_token"]}
    yield client, headers, calls
    client.close()
    get_settings.cache_clear()


def model_input(**changes):
    return {"provider_id": "custom", "protocol": "chat_completions", "base_url": "https://models.example.com/v1",
        "model": "synthetic-model", "credential_mode": "new", "api_key": "synthetic-key", "expected_revision": 0, **changes}


def test_preview_draft_and_activation_public_flow(workflow_client):
    client, headers, calls = workflow_client
    assert client.get("/settings/model/providers", headers=headers).status_code == 200
    result = client.post("/settings/model/preview/test", headers=headers, json=model_input())
    assert result.status_code == 200
    token = result.json()["data"]["verification_token"]
    assert token
    assert client.get("/settings/model/workspace", headers=headers).json()["data"]["revision"] == 0
    draft = client.put("/settings/model/draft", headers=headers, json=model_input())
    assert draft.status_code == 200
    assert draft.json()["data"]["active"] is None
    assert not draft.json()["data"]["draft"]["enabled"]
    stale = client.post("/settings/model/activate", headers=headers, json=model_input(verification_token=token))
    assert stale.status_code == 409
    payload = model_input(expected_revision=1, credential_mode="reuse_draft")
    payload.pop("api_key")
    token = client.post("/settings/model/preview/test", headers=headers, json=payload).json()["data"]["verification_token"]
    activated = client.post("/settings/model/activate", headers=headers, json={**payload, "verification_token": token})
    assert activated.status_code == 200
    assert activated.json()["data"]["active"]["enabled"]
    assert activated.json()["data"]["draft"] is None
    assert "synthetic-key" not in activated.text
    assert calls == ["generation", "structured", "close"] * 2


def test_old_put_cannot_enable_without_receipt(workflow_client):
    client, headers, calls = workflow_client
    response = client.put("/settings/model", headers=headers, json={"provider": "custom", "protocol": "chat_completions",
        "base_url": "https://models.example.com/v1", "model": "synthetic", "api_key": "synthetic-key", "enabled": True})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODEL_VERIFICATION_REQUIRED"
    assert calls == []


@pytest.mark.parametrize("path,method", [("/model/providers", "get"), ("/model/workspace", "get"),
    ("/model/preview/models", "post"), ("/model/preview/test", "post"),
    ("/model/draft", "put"), ("/model/activate", "post"), ("/model/disable", "post")])
def test_new_routes_require_authentication(workflow_client, path, method):
    client, _, _ = workflow_client
    response = getattr(client, method)("/settings" + path, **({"json": model_input()} if method != "get" else {}))
    assert response.status_code == 401
