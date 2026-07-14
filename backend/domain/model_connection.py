from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


ModelProvider = Literal["openai", "custom"]
ModelProtocol = Literal["responses", "chat_completions"]
ModelTestStatus = Literal["untested", "success", "failed"]
ModelConnectionState = Literal["unconfigured", "disabled", "untested", "success", "failed"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PublicModelConnection(BaseModel):
    provider: ModelProvider = "openai"
    protocol: ModelProtocol = "responses"
    base_url: str | None = None
    model: str = "gpt-5.5"
    enabled: bool = False
    api_key_configured: bool = False
    api_key_hint: str | None = None
    test_status: ModelTestStatus = "untested"
    test_error_code: str | None = None
    tested_at: str | None = None
    updated_at: str | None = None
    state: ModelConnectionState = "unconfigured"


class ModelConnection(BaseModel):
    provider: ModelProvider = "openai"
    protocol: ModelProtocol = "responses"
    base_url: str | None = None
    model: str = "gpt-5.5"
    encrypted_api_key: str | None = None
    api_key_hint: str | None = None
    enabled: bool = False
    test_status: ModelTestStatus = "untested"
    test_error_code: str | None = None
    tested_at: str | None = None
    updated_at: str = Field(default_factory=utc_now_iso)

    def to_public(self) -> PublicModelConnection:
        configured = bool(self.encrypted_api_key)
        if not configured:
            state: ModelConnectionState = "unconfigured"
        elif not self.enabled:
            state = "disabled"
        else:
            state = self.test_status
        return PublicModelConnection(
            provider=self.provider,
            protocol=self.protocol,
            base_url=self.base_url,
            model=self.model,
            enabled=self.enabled,
            api_key_configured=configured,
            api_key_hint=self.api_key_hint if configured else None,
            test_status=self.test_status,
            test_error_code=self.test_error_code,
            tested_at=self.tested_at,
            updated_at=self.updated_at,
            state=state,
        )
