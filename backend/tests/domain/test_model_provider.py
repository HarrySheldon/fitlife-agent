import pytest


def test_compatible_provider_is_added_as_data_not_business_code():
    from backend.domain.model_provider import ProviderPreset, ProviderRegistry
    registry = ProviderRegistry([ProviderPreset(id="synthetic", display_name="Synthetic",
        default_base_url="https://models.example.com/v1", protocols=("chat_completions",),
        recommended_protocol="chat_completions")])
    assert registry.resolve("synthetic", "chat_completions").display_name == "Synthetic"
    with pytest.raises(ValueError):
        registry.resolve("missing", "responses")
    with pytest.raises(ValueError):
        registry.resolve("synthetic", "responses")


def test_preset_cannot_register_executable_fields_or_unsupported_protocol():
    from pydantic import ValidationError
    from backend.domain.model_provider import ProviderPreset
    with pytest.raises(ValidationError):
        ProviderPreset(id="custom", display_name="Custom", default_base_url=None,
            protocols=("chat_completions",), recommended_protocol="responses")
    with pytest.raises(ValidationError):
        ProviderPreset(id="../bad", display_name="Bad", default_base_url=None,
            protocols=("chat_completions",), recommended_protocol="chat_completions")


def test_default_providers_include_major_openai_compatible_presets():
    from backend.domain.model_provider import DEFAULT_PROVIDERS

    presets = {item.id: item for item in DEFAULT_PROVIDERS.list()}
    expected_ids = {"deepseek", "openai", "dashscope", "siliconflow", "openrouter", "moonshot", "custom"}
    assert expected_ids.issubset(presets.keys())
    for preset_id in expected_ids - {"custom"}:
        preset = presets[preset_id]
        assert preset.default_base_url is not None and preset.default_base_url.startswith("https://")
        assert len(preset.recommended_models) >= 1
    assert presets["custom"].default_base_url is None
    assert presets["deepseek"].recommended_protocol == "chat_completions"
    assert presets["openai"].recommended_protocol == "responses"
