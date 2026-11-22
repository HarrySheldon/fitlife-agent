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
    recommended_models: tuple[str, ...] = ()

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
    ProviderPreset(
        id="deepseek",
        display_name="DeepSeek",
        default_base_url="https://api.deepseek.com/v1",
        protocols=("chat_completions",),
        recommended_protocol="chat_completions",
        recommended_models=("deepseek-chat", "deepseek-reasoner"),
    ),
    ProviderPreset(
        id="openai",
        display_name="OpenAI",
        default_base_url="https://api.openai.com/v1",
        protocols=("responses", "chat_completions"),
        recommended_protocol="responses",
        recommended_models=("gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"),
    ),
    ProviderPreset(
        id="dashscope",
        display_name="DashScope (Qwen)",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        protocols=("chat_completions",),
        recommended_protocol="chat_completions",
        recommended_models=("qwen-plus", "qwen-max", "qwen-turbo"),
    ),
    ProviderPreset(
        id="siliconflow",
        display_name="SiliconFlow",
        default_base_url="https://api.siliconflow.cn/v1",
        protocols=("chat_completions",),
        recommended_protocol="chat_completions",
        recommended_models=("deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct"),
    ),
    ProviderPreset(
        id="openrouter",
        display_name="OpenRouter",
        default_base_url="https://openrouter.ai/api/v1",
        protocols=("chat_completions",),
        recommended_protocol="chat_completions",
        recommended_models=("openai/gpt-4.1-mini", "anthropic/claude-sonnet-4"),
    ),
    ProviderPreset(
        id="moonshot",
        display_name="Moonshot (Kimi)",
        default_base_url="https://api.moonshot.cn/v1",
        protocols=("chat_completions",),
        recommended_protocol="chat_completions",
        recommended_models=("moonshot-v1-8k", "kimi-k2-0711-preview"),
    ),
    ProviderPreset(
        id="custom",
        display_name="Custom compatible service",
        default_base_url=None,
        protocols=("chat_completions", "responses"),
        recommended_protocol="chat_completions",
        recommended_models=(),
    ),
])
