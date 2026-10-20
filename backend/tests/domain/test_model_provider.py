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
