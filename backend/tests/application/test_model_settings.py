from dataclasses import replace

import pytest

from backend.application.use_cases.model_settings import (
    ClearModelApiKey,
    GetModelSettings,
    ListAvailableModels,
    ModelSettingsUpdate,
    SaveModelSettings,
    TestModelConnection,
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


class FakeGateway:
    model = "configured-model"

    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error

    def list_models(self) -> list[str]:
        return ["model-a", "model-b"]

    def probe_tool_call(self) -> None:
        if self.error:
            raise self.error


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


def test_model_list_is_an_explicit_operation_and_does_not_change_test_state():
    repository = MemoryRepository()
    repository.connections["user-a"] = ModelConnection(
        model="configured-model",
        encrypted_api_key="encrypted:terces",
        api_key_hint="********cret",
        enabled=True,
        test_status="untested",
    )

    result = ListAvailableModels(
        repository,
        ReversibleCipher(),
        lambda connection, api_key: FakeGateway(),
    ).execute("user-a")

    assert result == ["model-a", "model-b"]
    assert repository.connections["user-a"].test_status == "untested"


def test_model_list_normalizes_gateway_factory_failure():
    repository = MemoryRepository()
    repository.connections["user-a"] = ModelConnection(
        encrypted_api_key="encrypted:terces",
        api_key_hint="********cret",
        enabled=True,
    )

    with pytest.raises(ApplicationError) as raised:
        ListAvailableModels(
            repository,
            ReversibleCipher(),
            lambda connection, api_key: (_ for _ in ()).throw(RuntimeError("SDK internals")),
        ).execute("user-a")

    assert raised.value.code == "MODEL_PROTOCOL_ERROR"
    assert "SDK internals" not in raised.value.message


def test_connection_probe_saves_only_normalized_success_status():
    repository = MemoryRepository()
    repository.connections["user-a"] = ModelConnection(
        model="configured-model",
        encrypted_api_key="encrypted:terces",
        api_key_hint="********cret",
        enabled=True,
    )

    result = TestModelConnection(
        repository,
        ReversibleCipher(),
        lambda connection, api_key: FakeGateway(),
    ).execute("user-a")

    assert result.status == "success"
    assert result.model == "configured-model"
    stored = repository.connections["user-a"]
    assert stored.test_status == "success"
    assert stored.test_error_code is None
    assert stored.tested_at is not None


def test_connection_probe_normalizes_failure_without_storing_provider_details():
    repository = MemoryRepository()
    repository.connections["user-a"] = ModelConnection(
        encrypted_api_key="encrypted:terces",
        api_key_hint="********cret",
        enabled=True,
    )

    with pytest.raises(ApplicationError) as raised:
        TestModelConnection(
            repository,
            ReversibleCipher(),
            lambda connection, api_key: FakeGateway(error=TimeoutError("provider body secret")),
        ).execute("user-a")

    assert raised.value.code == "MODEL_TIMEOUT"
    stored = repository.connections["user-a"]
    assert stored.test_status == "failed"
    assert stored.test_error_code == "MODEL_TIMEOUT"
    assert "provider body secret" not in stored.model_dump_json()
