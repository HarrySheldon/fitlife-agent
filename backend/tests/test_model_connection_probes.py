from types import SimpleNamespace as NS

import pytest

from backend.infrastructure.model_gateway.openai_responses import OpenAIResponsesAdapter
from backend.infrastructure.model_gateway.openai_chat_completions import OpenAIChatCompletionsAdapter


def make_probe_adapter(protocol, *, arguments='{"ok": true}', text="OK"):
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return NS(output_text=text, output=[NS(type="function_call", name="connection_probe", arguments=arguments)],
            choices=[NS(message=NS(content=text, tool_calls=[NS(function=NS(name="connection_probe", arguments=arguments))]))])
    api = NS(create=create)
    client = NS(responses=api, chat=NS(completions=api))
    adapter_class = OpenAIResponsesAdapter if protocol == "responses" else OpenAIChatCompletionsAdapter
    return adapter_class(client=client, model="synthetic"), calls


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
def test_generation_probe_has_bounded_output_and_nonempty_response(protocol):
    adapter, calls = make_probe_adapter(protocol)
    adapter.probe_generation()
    assert (calls[0].get("max_output_tokens") or calls[0].get("max_completion_tokens")) == 128
    assert calls[0]["timeout"] <= 30


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
@pytest.mark.parametrize("arguments", ['{"ok": false}', '{"ok": "true"}', '{"ok": 1}', '{}', 'invalid', '[]'])
def test_tool_probe_rejects_invalid_arguments(protocol, arguments):
    adapter, _ = make_probe_adapter(protocol, arguments=arguments)
    with pytest.raises(ValueError):
        adapter.probe_tool_call()


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
def test_generation_rejects_whitespace(protocol):
    adapter, _ = make_probe_adapter(protocol, text="  ")
    with pytest.raises(ValueError):
        adapter.probe_generation()


def test_legacy_default_address_is_explicit_not_sdk_environment_dependent(monkeypatch):
    import sys
    from backend.domain.model_connection import ModelConnection
    from backend.infrastructure.model_gateway.factory import create_model_gateway
    captured = {}
    def constructor(**kwargs):
        captured.update(kwargs)
        return NS()
    monkeypatch.setitem(sys.modules, "openai", NS(OpenAI=constructor))
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unexpected.example.com/v1")
    try:
        create_model_gateway(ModelConnection(provider="openai", base_url=None), "synthetic-key")
        assert captured["base_url"] == "https://api.openai.com/v1"
        assert captured["max_retries"] == 0
    finally:
        if "http_client" in captured:
            captured["http_client"].close()


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
def test_business_probe_uses_plain_json_and_local_validation(protocol):
    adapter, calls = make_probe_adapter(protocol, text='{"food":"oats","amount":40,"unit":"g"}')
    adapter.structured_mode = "json"
    adapter.probe_structured()
    sent = calls[0]
    assert not {"tools", "tool_choice", "response_format", "text_format"} & sent.keys()
    assert (sent.get("max_output_tokens") or sent.get("max_completion_tokens")) == 128
    assert "oats 40 g" in str(sent)


@pytest.mark.parametrize("text", ['not JSON', '{"food":"oats","amount":"40","unit":"g"}',
    '{"food":"oats","amount":41,"unit":"g"}', '{"food":"oats","amount":40,"unit":"kg"}',
    '{"food":"oats","amount":40,"unit":"g","extra":true}'])
@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
def test_business_probe_rejects_invalid_result(protocol, text):
    adapter, _ = make_probe_adapter(protocol, text=text)
    adapter.structured_mode = "json"
    with pytest.raises(ValueError):
        adapter.probe_structured()


def test_custom_deepseek_gateway_probes_and_business_share_json_path():
    from backend.domain.model_connection import ModelConnection
    from backend.domain.model_endpoint_policy import ModelEndpointPolicy
    from backend.infrastructure.model_gateway.factory import create_model_gateway
    from pydantic import BaseModel
    calls = []
    texts = iter(['{"food":"oats","amount":40,"unit":"g"}', '{"value":"ok"}', '{"intent":"knowledge_qa"}'])
    def create(**kwargs):
        calls.append(kwargs)
        return NS(choices=[NS(message=NS(content=next(texts)))])
    class Output(BaseModel):
        value: str
    policy = ModelEndpointPolicy(resolver=lambda *_args, **_kwargs: [(None, None, None, None, ("8.8.8.8", 443))])
    gateway = create_model_gateway(ModelConnection(provider="custom", protocol="chat_completions",
        base_url="https://api.deepseek.com", model="synthetic"), "synthetic-key",
        client=NS(chat=NS(completions=NS(create=create))), endpoint_policy=policy)
    gateway.probe_structured()
    assert gateway.parse_structured(instructions="Extract", input_text="input", response_model=Output).output.value == "ok"
    assert gateway.plan_route("question").intent == "knowledge_qa"
    assert calls[0]["max_tokens"] == 128
    assert all(not {"tools", "tool_choice", "response_format"} & call.keys() for call in calls)


@pytest.mark.parametrize("provider,address,mode,token_field", [
    ("openai", "https://api.openai.com/v1", "native", "max_completion_tokens"),
    ("openai", "https://third-party.example.com/v1", "json", "max_completion_tokens"),
    ("custom", "https://api.openai.com/v1", "json", "max_completion_tokens"),
    ("custom", "https://api.deepseek.com", "json", "max_tokens"),
    ("custom", "https://api.deepseek.com.other.example.com", "json", "max_completion_tokens"),
])
def test_factory_compatibility_uses_actual_destination(provider, address, mode, token_field):
    from backend.domain.model_connection import ModelConnection
    from backend.domain.model_endpoint_policy import ModelEndpointPolicy
    from backend.infrastructure.model_gateway.factory import create_model_gateway
    policy = ModelEndpointPolicy(resolver=lambda *_args, **_kwargs: [(None, None, None, None, ("8.8.8.8", 443))])
    gateway = create_model_gateway(ModelConnection(provider=provider, protocol="chat_completions",
        base_url=address, model="synthetic"), "synthetic-key", client=NS(), endpoint_policy=policy)
    assert gateway.structured_mode == mode
    assert gateway.max_tokens_field == token_field


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
def test_native_business_probe_uses_same_parser_and_restores_output_limit(protocol):
    from backend.application.ports.model_call_context import model_output_limit
    from backend.domain.model_connection_probe import ConnectionBusinessSample
    calls = []
    def parse(**kwargs):
        calls.append(kwargs)
        schema = kwargs.get("text_format") or kwargs.get("response_format")
        assert schema is ConnectionBusinessSample
        parsed = schema(food="oats", amount=40, unit="g")
        return NS(output=[NS(type="message", content=[NS(type="output_text", parsed=parsed)])],
            choices=[NS(message=NS(parsed=parsed))])
    api = NS(parse=parse)
    adapter_class = OpenAIResponsesAdapter if protocol == "responses" else OpenAIChatCompletionsAdapter
    gateway = adapter_class(client=NS(responses=api, chat=NS(completions=api)), model="synthetic")
    previous = model_output_limit.set(256)
    try:
        gateway.probe_structured()
        assert (calls[0].get("max_output_tokens") or calls[0].get("max_completion_tokens")) == 128
        assert model_output_limit.get() == 256
    finally:
        model_output_limit.reset(previous)
