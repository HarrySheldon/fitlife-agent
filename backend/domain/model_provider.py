"""Data-only provider presets. Protocol implementations live in the gateway package."""
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.domain.model_connection import ModelProtocol


class ProviderPreset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    display_name: str = Field(min_length=1, max_length=100)
    default_base_url: str | None
    protocols: tuple[ModelProtocol, ...] = Field(min_length=1)
    recommended_protocol: ModelProtocol

    @model_validator(mode="after")
    def supported_recommendation(self):
        if self.recommended_protocol not in self.protocols:
            raise ValueError("Recommended protocol must be supported")
        return self


class ProviderRegistry:
    def __init__(self, presets: list[ProviderPreset]):
        self._presets = {preset.id: preset for preset in presets}
        if len(self._presets) != len(presets):
            raise ValueError("Duplicate provider id")

    def list(self) -> list[ProviderPreset]:
        return list(self._presets.values())

    def resolve(self, provider_id: str, protocol: ModelProtocol) -> ProviderPreset:
        preset = self._presets.get(provider_id)
        if preset is None or protocol not in preset.protocols:
            raise ValueError("Unsupported provider or protocol")
        return preset


DEFAULT_PROVIDERS = ProviderRegistry([
    ProviderPreset(id="custom", display_name="Custom compatible service", default_base_url=None,
        protocols=("chat_completions", "responses"), recommended_protocol="chat_completions"),
    ProviderPreset(id="openai", display_name="OpenAI", default_base_url="https://api.openai.com/v1",
        protocols=("responses", "chat_completions"), recommended_protocol="responses"),
])
