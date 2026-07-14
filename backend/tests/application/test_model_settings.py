from dataclasses import replace

import pytest

from backend.application.use_cases.model_settings import (
    ClearModelApiKey,
    GetModelSettings,
    ModelSettingsUpdate,
    SaveModelSettings,
)
from backend.domain.errors import ApplicationError
from backend.domain.model_connection import ModelConnection


class MemoryRepository:
    def __init__(self) -> None:
        self.connections: dict[str, ModelConnection] = {}

    def get(self, user_id: str) -> ModelConnection | None:
        return self.connections.get(user_id)

    def save(self, user_id: str, connection: ModelConnection) -> None:
        self.connections[user_id] = connection


class ReversibleCipher:
    def encrypt(self, plaintext: str) -> str:
        return f"encrypted:{plaintext[::-1]}"

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext.removeprefix("encrypted:")[::-1]


def update(**changes) -> ModelSettingsUpdate:
    defaults = ModelSettingsUpdate(
        provider="openai",
        protocol="responses",
        base_url=None,
        model="gpt-5.5",
        enabled=True,
    )
    return replace(defaults, **changes)


def test_get_returns_unconfigured_default_without_creating_storage():
    repository = MemoryRepository()

    result = GetModelSettings(repository).execute("user-a")

    assert result.state == "unconfigured"
    assert result.api_key_configured is False
    assert repository.connections == {}


def test_save_encrypts_new_key_and_public_result_never_exposes_it():
    repository = MemoryRepository()

    result = SaveModelSettings(repository, ReversibleCipher()).execute(
        "user-a",
        update(api_key="sk-user-secret"),
    )

    stored = repository.connections["user-a"]
    assert stored.encrypted_api_key == "encrypted:terces-resu-ks"
    assert stored.api_key_hint == "********cret"
    assert result.api_key_configured is True
    assert "encrypted_api_key" not in result.model_dump()


def test_save_without_key_retains_existing_key_and_test_state():
    repository = MemoryRepository()
    repository.connections["user-a"] = ModelConnection(
        encrypted_api_key="existing-ciphertext",
        api_key_hint="********ting",
        enabled=False,
        test_status="success",
        tested_at="2026-07-12T01:02:03+00:00",
    )

    result = SaveModelSettings(repository, None).execute("user-a", update(enabled=True))

    stored = repository.connections["user-a"]
    assert stored.encrypted_api_key == "existing-ciphertext"
    assert stored.api_key_hint == "********ting"
    assert stored.test_status == "success"
    assert result.enabled is True


@pytest.mark.parametrize("field,value", [("model", "gpt-new"), ("protocol", "chat_completions")])
def test_material_change_resets_previous_test_state(field, value):
    repository = MemoryRepository()
    repository.connections["user-a"] = ModelConnection(
        encrypted_api_key="existing-ciphertext",
        api_key_hint="********ting",
        enabled=True,
        test_status="failed",
        test_error_code="MODEL_AUTH_FAILED",
        tested_at="2026-07-12T01:02:03+00:00",
    )

    SaveModelSettings(repository, None).execute("user-a", update(**{field: value}))

    stored = repository.connections["user-a"]
    assert stored.test_status == "untested"
    assert stored.test_error_code is None
    assert stored.tested_at is None


def test_clear_key_is_explicit_and_resets_test_state():
    repository = MemoryRepository()
    repository.connections["user-a"] = ModelConnection(
        encrypted_api_key="existing-ciphertext",
        api_key_hint="********ting",
        enabled=True,
        test_status="success",
        tested_at="2026-07-12T01:02:03+00:00",
    )

    result = ClearModelApiKey(repository).execute("user-a")

    stored = repository.connections["user-a"]
    assert stored.encrypted_api_key is None
    assert stored.api_key_hint is None
    assert stored.test_status == "untested"
    assert stored.tested_at is None
    assert result.state == "unconfigured"


def test_saving_new_key_requires_deployment_cipher():
    repository = MemoryRepository()

    with pytest.raises(ApplicationError) as raised:
        SaveModelSettings(repository, None).execute("user-a", update(api_key="sk-user-secret"))

    assert raised.value.code == "CREDENTIAL_STORE_UNAVAILABLE"
    assert repository.connections == {}
