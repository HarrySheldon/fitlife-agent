import json
from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.model_connection import ModelConnection
from backend.infrastructure.settings.fernet_cipher import FernetCredentialCipher
from backend.infrastructure.settings.file_model_connection_repository import FileModelConnectionRepository


def make_data_dir() -> Path:
    return Path(".tmp") / "pytest-model-settings" / uuid4().hex


def test_fernet_cipher_round_trip_never_embeds_plaintext():
    cipher = FernetCredentialCipher.generate()

    encrypted = cipher.encrypt("sk-user-secret")

    assert encrypted != "sk-user-secret"
    assert "sk-user-secret" not in encrypted
    assert cipher.decrypt(encrypted) == "sk-user-secret"


def test_file_repository_atomically_isolates_users(monkeypatch):
    data_dir = make_data_dir()
    repository = FileModelConnectionRepository(data_dir)
    replace_calls: list[tuple[Path, Path]] = []
    real_replace = repository.replace_file
    monkeypatch.setattr(
        repository,
        "replace_file",
        lambda source, destination: (replace_calls.append((source, destination)), real_replace(source, destination))[1],
    )
    connection = ModelConnection(
        provider="custom",
        protocol="responses",
        base_url="https://models.example.com/v1",
        model="fit-model",
        encrypted_api_key="encrypted-value",
        api_key_hint="********cret",
        enabled=True,
    )

    repository.save("user-a", connection)

    assert repository.get("user-a") == connection
    assert repository.get("user-b") is None
    assert len(replace_calls) == 1
    assert replace_calls[0][1].name == "model_connection.json"
    stored = json.loads((data_dir / "users" / "user-a" / "model_connection.json").read_text(encoding="utf-8"))
    assert stored["encrypted_api_key"] == "encrypted-value"


def test_public_connection_never_contains_ciphertext():
    connection = ModelConnection(
        provider="openai",
        protocol="responses",
        model="gpt-test",
        encrypted_api_key="ciphertext-must-stay-server-side",
        api_key_hint="********test",
        enabled=True,
    )

    public = connection.to_public().model_dump()

    assert public["api_key_configured"] is True
    assert public["api_key_hint"] == "********test"
    assert "encrypted_api_key" not in public
    assert "ciphertext-must-stay-server-side" not in json.dumps(public)


def test_repository_explicitly_clears_stored_key():
    data_dir = make_data_dir()
    repository = FileModelConnectionRepository(data_dir)
    repository.save(
        "user-a",
        ModelConnection(
            encrypted_api_key="encrypted-value",
            api_key_hint="********alue",
            enabled=True,
        ),
    )

    repository.save("user-a", ModelConnection())

    stored = repository.get("user-a")
    assert stored is not None
    assert stored.encrypted_api_key is None
    assert stored.api_key_hint is None
    assert stored.to_public().state == "unconfigured"
    payload = (data_dir / "users" / "user-a" / "model_connection.json").read_text(encoding="utf-8")
    assert "encrypted-value" not in payload


def test_repository_rejects_path_traversal_user_id():
    repository = FileModelConnectionRepository(make_data_dir())

    with pytest.raises(ValueError, match="Invalid user id"):
        repository.save("../other-user", ModelConnection())
