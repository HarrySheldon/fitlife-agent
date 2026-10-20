"""Strict transport-neutral inputs for preview and workspace operations."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from backend.domain.model_connection import ModelProtocol


class ModelConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    protocol: ModelProtocol
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(default="", max_length=200)
    expected_revision: int = Field(ge=0)
    credential_mode: Literal["new", "reuse_active", "reuse_draft"]
    api_key: SecretStr | None = None
    confirm_credential_reuse: bool = False

    @model_validator(mode="after")
    def credential_choice(self):
        if self.credential_mode == "new":
            value = self.api_key.get_secret_value().strip() if self.api_key else ""
            if not value or len(value) > 4096:
                raise ValueError("A new credential must be provided")
        elif self.api_key is not None:
            raise ValueError("Credential reuse cannot include a new key")
        return self


class ModelActivationInput(ModelConnectionInput):
    verification_token: str = Field(min_length=1, max_length=4096)


class ModelRevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)


class ModelClearCredentialInput(ModelRevisionInput):
    slot: Literal["active", "draft"]
