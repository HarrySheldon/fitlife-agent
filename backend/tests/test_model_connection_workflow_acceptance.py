"""Offline user-level acceptance, including the real account lifecycle and resolver."""
import io
import json
from types import SimpleNamespace
from zipfile import ZipFile

from backend.tests.test_model_connection_workflow_api import workflow_client, model_input


def test_offline_setup_export_activation_and_account_removal(workflow_client):
    from backend.config import get_settings
    from backend.infrastructure.model_gateway.factory import resolve_user_model_gateway
    from backend.infrastructure.sqlite.runtime import initialize_database
    from backend.task_evaluation.network import install_network_guard

    client, headers, calls = workflow_client
    restore = install_network_guard()
    try:
        initialize_database()
        listed = client.post("/settings/model/preview/models", headers=headers, json=model_input(model=""))
        assert listed.status_code == 200
        assert listed.json()["data"]["models"] == ["synthetic-model"]
        draft = client.put("/settings/model/draft", headers=headers, json=model_input())
        assert draft.status_code == 200
        exported = client.get("/account/export", headers=headers)
        assert exported.status_code == 200
        with ZipFile(io.BytesIO(exported.content)) as archive:
            contents = b"\n".join(archive.read(name) for name in archive.namelist())
            draft_export = json.loads(archive.read("model-connection-draft.json"))
            assert draft_export["model"] == "synthetic-model"
            assert draft_export["provider_id"] == "custom"
            assert draft_export["generation_status"] == draft_export["structured_status"] == "not_run"
        assert b"synthetic-key" not in contents
        assert b"encrypted_api_key" not in contents
        assert b"api_key_hint" not in contents
        assert b"credential_fingerprint" not in contents
        assert calls == ["list", "close"]

        payload = model_input(expected_revision=1, credential_mode="reuse_draft")
        payload.pop("api_key")
        probed = client.post("/settings/model/preview/test", headers=headers, json=payload)
        assert probed.status_code == 200
        token = probed.json()["data"]["verification_token"]
        activated = client.post("/settings/model/activate", headers=headers, json={**payload, "verification_token": token})
        assert activated.status_code == 200
        assert calls == ["list", "close", "generation", "structured", "close"]
        active_export = client.get("/account/export", headers=headers)
        assert active_export.status_code == 200
        with ZipFile(io.BytesIO(active_export.content)) as archive:
            active_metadata = json.loads(archive.read("model-connection.json"))
            assert active_metadata["provider_id"] == "custom"
            assert active_metadata["generation_status"] == active_metadata["structured_status"] == "passed"
            assert active_metadata["tool_status"] == "not_run"
        session = headers["Authorization"].split()[1]
        from backend.tools.auth_store import user_from_token
        user_id = user_from_token(session).user_id
        captured = []
        def factory(connection, key):
            captured.append((connection.model, key))
            return SimpleNamespace(model=connection.model)
        gateway = resolve_user_model_gateway(user_id, gateway_factory=factory)
        assert gateway.model == "synthetic-model"
        assert captured == [("synthetic-model", "synthetic-key")]
        user_root = get_settings().data_dir / "users" / user_id
        deleted = client.request("DELETE", "/account", headers=headers,
            json={"password": "password123", "confirmation": "DELETE"})
        assert deleted.status_code == 200
        assert not user_root.exists()
        assert client.get("/settings/model/workspace", headers=headers).status_code == 401
        assert client.post("/settings/model/activate", headers=headers,
            json={**payload, "verification_token": token}).status_code == 401
        assert not user_root.exists()
    finally:
        restore()
