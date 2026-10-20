from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ModelProvider = Literal["openai", "custom"]
ModelProtocol = Literal["responses", "chat_completions"]
ModelTestStatus = Literal["untested", "success", "failed"]
ModelConnectionState = Literal["unconfigured", "disabled", "untested", "success", "failed"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def credential_hint(credential: str) -> str:
    return "********" + (credential[-4:] if len(credential) > 4 else "")


class PublicModelConnection(BaseModel):
    provider_id: str | None = None
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
    generation_status: Literal["passed", "failed", "not_run"] = "not_run"
    tool_status: Literal["passed", "failed", "not_run"] = "not_run"
    structured_status: Literal["passed", "failed", "not_run"] = "not_run"


class ModelConnection(BaseModel):
    provider_id: str | None = None
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
    generation_status: Literal["passed", "failed", "not_run"] = "not_run"
    tool_status: Literal["passed", "failed", "not_run"] = "not_run"
    structured_status: Literal["passed", "failed", "not_run"] = "not_run"

    def to_public(self) -> PublicModelConnection:
        configured = bool(self.encrypted_api_key)
        if not configured:
            state: ModelConnectionState = "unconfigured"
        elif not self.enabled:
            state = "disabled"
        else:
            state = self.test_status
        return PublicModelConnection(
            provider_id=self.provider_id or self.provider,
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
            generation_status=self.generation_status,
            tool_status=self.tool_status,
            structured_status=self.structured_status,
        )


class ModelConnectionTestResult(BaseModel):
    status: Literal["success"] = "success"
    protocol: ModelProtocol
    model: str
    latency_ms: int = Field(ge=0)
    tested_at: str


class PublicModelConnectionWorkspace(BaseModel):
    revision: int
    active: PublicModelConnection | None = None
    draft: PublicModelConnection | None = None


class ModelConnectionWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    revision: int = Field(default=0, ge=0)
    active: ModelConnection | None = None
    draft: ModelConnection | None = None

    @model_validator(mode="after")
    def disabled_draft(self):
        if self.draft is not None and self.draft.enabled:
            raise ValueError("Draft connections must be disabled")
        return self

    def to_public(self) -> PublicModelConnectionWorkspace:
        return PublicModelConnectionWorkspace(
            revision=self.revision,
            active=self.active.to_public() if self.active else None,
            draft=self.draft.to_public() if self.draft else None,
        )
