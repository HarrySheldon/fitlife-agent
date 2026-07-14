from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from backend.application.ports.credential_cipher import CredentialCipher
from backend.application.ports.model_connection_repository import ModelConnectionRepository
from backend.application.ports.model_gateway import ConfigurableModelGateway
from backend.config import Settings, get_settings
from backend.domain.errors import ai_disabled_error, ai_not_configured_error, credential_store_unavailable_error
from backend.domain.model_connection import ModelConnection
from backend.domain.model_endpoint_policy import ModelEndpointPolicy
from backend.infrastructure.model_gateway.openai_chat_completions import OpenAIChatCompletionsAdapter
from backend.infrastructure.model_gateway.openai_responses import OpenAIResponsesAdapter
from backend.infrastructure.settings.fernet_cipher import FernetCredentialCipher
from backend.infrastructure.settings.file_model_connection_repository import FileModelConnectionRepository


ModelGatewayFactory = Callable[[ModelConnection, str], ConfigurableModelGateway]


class EndpointPolicyTransport(httpx.BaseTransport):
    def __init__(self, policy: ModelEndpointPolicy) -> None:
        self.policy = policy
        self.transport = httpx.HTTPTransport(retries=0)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.policy.validate_request_url(str(request.url))
        return self.transport.handle_request(request)

    def close(self) -> None:
        self.transport.close()


def create_model_gateway(
    connection: ModelConnection,
    api_key: str,
    *,
    client: Any | None = None,
    endpoint_policy: ModelEndpointPolicy | None = None,
) -> ConfigurableModelGateway:
    policy = endpoint_policy or ModelEndpointPolicy()
    base_url = None
    if connection.provider == "custom":
        if not connection.base_url:
            from backend.domain.errors import invalid_model_endpoint_error

            raise invalid_model_endpoint_error()
        base_url = policy.validate_base_url(connection.base_url)

    if client is None:
        from openai import OpenAI

        http_client = httpx.Client(
            transport=EndpointPolicyTransport(policy),
            follow_redirects=False,
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        kwargs: dict[str, Any] = {"api_key": api_key, "http_client": http_client}
        if base_url:
            kwargs["base_url"] = base_url
        client = OpenAI(**kwargs)

    if connection.protocol == "chat_completions":
        return OpenAIChatCompletionsAdapter(client=client, model=connection.model)
    return OpenAIResponsesAdapter(client=client, model=connection.model)


def resolve_user_model_gateway(
    user_id: str,
    *,
    repository: ModelConnectionRepository | None = None,
    cipher: CredentialCipher | None = None,
    settings: Settings | None = None,
    gateway_factory: ModelGatewayFactory | None = None,
) -> ConfigurableModelGateway:
    settings = settings or get_settings()
    repository = repository or FileModelConnectionRepository(settings.data_dir)
    connection = repository.get(user_id)
    if connection is None:
        raise ai_not_configured_error()
    if not connection.enabled:
        raise ai_disabled_error()
    if not connection.encrypted_api_key:
        raise ai_not_configured_error()

    cipher = cipher or _settings_cipher(settings)
    if cipher is None:
        raise credential_store_unavailable_error(processing_mode="agent")
    try:
        api_key = cipher.decrypt(connection.encrypted_api_key)
    except Exception:
        raise credential_store_unavailable_error(processing_mode="agent") from None

    factory = gateway_factory or create_model_gateway
    return factory(connection, api_key)


def _settings_cipher(settings: Settings) -> FernetCredentialCipher | None:
    if not settings.settings_encryption_key:
        return None
    try:
        return FernetCredentialCipher(settings.settings_encryption_key)
    except ValueError:
        return None
