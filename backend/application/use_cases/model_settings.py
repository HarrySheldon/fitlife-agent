from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable

from backend.application.ports.credential_cipher import CredentialCipher
from backend.application.ports.model_connection_repository import ModelConnectionRepository
from backend.application.ports.model_gateway import ConfigurableModelGateway
from backend.domain.errors import (
    ApplicationError,
    ai_not_configured_error,
    credential_store_unavailable_error,
    model_gateway_error,
)
from backend.domain.model_connection import (
    ModelConnection,
    ModelConnectionTestResult,
    ModelProtocol,
    ModelProvider,
    PublicModelConnection,
    utc_now_iso,
)


ModelGatewayFactory = Callable[[ModelConnection, str], ConfigurableModelGateway]


@dataclass(frozen=True)
class ModelSettingsUpdate:
    provider: ModelProvider
    protocol: ModelProtocol
    base_url: str | None
    model: str
    enabled: bool
    api_key: str | None = None


class GetModelSettings:
    def __init__(self, repository: ModelConnectionRepository) -> None:
        self.repository = repository

    def execute(self, user_id: str) -> PublicModelConnection:
        connection = self.repository.get(user_id) or ModelConnection()
        return connection.to_public()


class SaveModelSettings:
    def __init__(
        self,
        repository: ModelConnectionRepository,
        cipher: CredentialCipher | None,
    ) -> None:
        self.repository = repository
        self.cipher = cipher

    def execute(self, user_id: str, update: ModelSettingsUpdate) -> PublicModelConnection:
        current = self.repository.get(user_id) or ModelConnection()
        api_key = update.api_key.strip() if update.api_key is not None else None
        if update.api_key is not None and not api_key:
            raise ValueError("API key cannot be blank")

        encrypted_api_key = current.encrypted_api_key
        api_key_hint = current.api_key_hint
        if api_key is not None:
            if self.cipher is None:
                raise credential_store_unavailable_error()
            encrypted_api_key = self.cipher.encrypt(api_key)
            api_key_hint = _api_key_hint(api_key)

        provider = update.provider
        base_url = update.base_url.strip() if update.base_url else None
        if provider == "openai":
            base_url = None
        model = update.model.strip()
        if not model:
            raise ValueError("Model cannot be blank")

        material_changed = api_key is not None or (
            provider,
            update.protocol,
            base_url,
            model,
        ) != (
            current.provider,
            current.protocol,
            current.base_url,
            current.model,
        )
        saved = current.model_copy(
            update={
                "provider": provider,
                "protocol": update.protocol,
                "base_url": base_url,
                "model": model,
                "encrypted_api_key": encrypted_api_key,
                "api_key_hint": api_key_hint,
                "enabled": update.enabled,
                "test_status": "untested" if material_changed else current.test_status,
                "test_error_code": None if material_changed else current.test_error_code,
                "tested_at": None if material_changed else current.tested_at,
                "updated_at": utc_now_iso(),
            }
        )
        self.repository.save(user_id, saved)
        return saved.to_public()


class ClearModelApiKey:
    def __init__(self, repository: ModelConnectionRepository) -> None:
        self.repository = repository

    def execute(self, user_id: str) -> PublicModelConnection:
        current = self.repository.get(user_id) or ModelConnection()
        saved = current.model_copy(
            update={
                "encrypted_api_key": None,
                "api_key_hint": None,
                "test_status": "untested",
                "test_error_code": None,
                "tested_at": None,
                "updated_at": utc_now_iso(),
            }
        )
        self.repository.save(user_id, saved)
        return saved.to_public()


class ListAvailableModels:
    def __init__(
        self,
        repository: ModelConnectionRepository,
        cipher: CredentialCipher | None,
        gateway_factory: ModelGatewayFactory,
    ) -> None:
        self.repository = repository
        self.cipher = cipher
        self.gateway_factory = gateway_factory

    def execute(self, user_id: str) -> list[str]:
        connection = self.repository.get(user_id) or ModelConnection()
        try:
            gateway = _resolve_gateway(connection, self.cipher, self.gateway_factory)
            return gateway.list_models()
        except ApplicationError:
            raise
        except Exception as error:
            raise model_gateway_error(error) from None


class TestModelConnection:
    __test__ = False

    def __init__(
        self,
        repository: ModelConnectionRepository,
        cipher: CredentialCipher | None,
        gateway_factory: ModelGatewayFactory,
    ) -> None:
        self.repository = repository
        self.cipher = cipher
        self.gateway_factory = gateway_factory

    def execute(self, user_id: str) -> ModelConnectionTestResult:
        connection = self.repository.get(user_id) or ModelConnection()
        started = perf_counter()
        try:
            gateway = _resolve_gateway(connection, self.cipher, self.gateway_factory)
            gateway.probe_tool_call()
        except ApplicationError as error:
            self._save_failure(user_id, connection, error.code)
            raise
        except Exception as error:
            normalized = model_gateway_error(error)
            self._save_failure(user_id, connection, normalized.code)
            raise normalized from None

        tested_at = utc_now_iso()
        saved = connection.model_copy(
            update={
                "test_status": "success",
                "test_error_code": None,
                "tested_at": tested_at,
                "updated_at": tested_at,
            }
        )
        self.repository.save(user_id, saved)
        return ModelConnectionTestResult(
            protocol=connection.protocol,
            model=connection.model,
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            tested_at=tested_at,
        )

    def _save_failure(self, user_id: str, connection: ModelConnection, code: str) -> None:
        tested_at = utc_now_iso()
        self.repository.save(
            user_id,
            connection.model_copy(
                update={
                    "test_status": "failed",
                    "test_error_code": code,
                    "tested_at": tested_at,
                    "updated_at": tested_at,
                }
            ),
        )


def _api_key_hint(api_key: str) -> str:
    return f"********{api_key[-4:]}"


def _resolve_gateway(
    connection: ModelConnection,
    cipher: CredentialCipher | None,
    gateway_factory: ModelGatewayFactory,
) -> ConfigurableModelGateway:
    if not connection.encrypted_api_key:
        raise ai_not_configured_error()
    if cipher is None:
        raise credential_store_unavailable_error(processing_mode="agent")
    try:
        api_key = cipher.decrypt(connection.encrypted_api_key)
    except Exception:
        raise credential_store_unavailable_error(processing_mode="agent") from None
    return gateway_factory(connection, api_key)
