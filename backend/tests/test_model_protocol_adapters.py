from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from backend.agent.planner import PlannerRoute
from backend.config import Settings
from backend.domain.model_connection import ModelConnection
from backend.infrastructure.model_gateway.factory import create_model_gateway
from backend.infrastructure.model_gateway.openai_chat_completions import OpenAIChatCompletionsAdapter
from backend.infrastructure.model_gateway.openai_responses import (
    OpenAIResponsesAdapter,
    build_model_gateway,
)


class ResponsesApi:
    def __init__(self) -> None:
        self.create_calls: list[dict] = []
        self.parse_calls: list[dict] = []

    def parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        output_type = kwargs["text_format"]
        parsed = (
            StrictExample(value="ok")
            if output_type is StrictExample
            else PlannerRoute(intent="knowledge_qa")
        )
        content = SimpleNamespace(type="output_text", parsed=parsed)
        return SimpleNamespace(
            output=[SimpleNamespace(type="message", content=[content])],
            model="resolved-responses-model",
            usage=SimpleNamespace(
                input_tokens=11,
                output_tokens=7,
                total_tokens=18,
            ),
        )

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        if "tools" in kwargs:
            return SimpleNamespace(
                output=[SimpleNamespace(type="function_call", name="connection_probe")],
                output_text="",
            )
        return SimpleNamespace(output=[], output_text="## Responses answer")


class ChatCompletionsApi:
    def __init__(self) -> None:
        self.create_calls: list[dict] = []

    def parse(self, **kwargs):
        output_type = kwargs["response_format"]
        parsed = (
            StrictExample(value="ok")
            if output_type is StrictExample
            else PlannerRoute(intent="knowledge_qa")
        )
        message = SimpleNamespace(parsed=parsed, content=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            model="resolved-chat-model",
            usage=SimpleNamespace(
                prompt_tokens=13,
                completion_tokens=5,
                total_tokens=18,
            ),
        )

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        if "tools" in kwargs:
            tool_call = SimpleNamespace(function=SimpleNamespace(name="connection_probe"))
            message = SimpleNamespace(content=None, tool_calls=[tool_call])
        else:
            message = SimpleNamespace(content="## Chat answer", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class ModelsApi:
    def list(self):
        return SimpleNamespace(data=[SimpleNamespace(id="model-b"), SimpleNamespace(id="model-a")])


class MissingStructuredRouteResponses:
    """A response whose message carries no parsed structured payload."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        content = SimpleNamespace(type="output_text", parsed=None)
        return SimpleNamespace(output=[SimpleNamespace(type="message", content=[content])])

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text="")


class BlankAnswerResponses:
    """A response that returns no answer text at all."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        parsed = PlannerRoute(intent="knowledge_qa")
        content = SimpleNamespace(type="output_text", parsed=parsed)
        return SimpleNamespace(output=[SimpleNamespace(type="message", content=[content])])

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text="   ")


class StrictExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str


def test_responses_adapter_supports_unified_planner_writer_list_and_probe():
    responses = ResponsesApi()
    client = SimpleNamespace(responses=responses, models=ModelsApi())
    adapter = OpenAIResponsesAdapter(client=client, model="response-model")

    assert adapter.plan_route("question").intent == "knowledge_qa"
    assert adapter.write_answer({"user_query": "question"}) == "## Responses answer"
    assert adapter.list_models() == ["model-a", "model-b"]
    adapter.probe_tool_call()
    assert responses.create_calls[-1]["tool_choice"]["name"] == "connection_probe"


def test_responses_writer_distinguishes_ui_locale_from_answer_language():
    responses = ResponsesApi()
    client = SimpleNamespace(responses=responses, models=ModelsApi())
    adapter = OpenAIResponsesAdapter(client=client, model="response-model")

    adapter.write_answer(
        {
            "user_query": "Please answer this question in English.",
            "context_metadata": {"language": "zh-CN"},
        }
    )

    instructions = responses.create_calls[-1]["instructions"]
    assert "context_metadata.language is the UI locale only" in instructions
    assert "The language of user_query controls the answer language" in instructions


def test_chat_completions_adapter_supports_unified_planner_writer_list_and_probe():
    completions = ChatCompletionsApi()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions), models=ModelsApi())
    adapter = OpenAIChatCompletionsAdapter(client=client, model="chat-model")

    assert adapter.plan_route("question").intent == "knowledge_qa"
    assert adapter.write_answer({"user_query": "question"}) == "## Chat answer"
    assert adapter.list_models() == ["model-a", "model-b"]
    adapter.probe_tool_call()
    assert completions.create_calls[-1]["tool_choice"]["function"]["name"] == "connection_probe"


def test_both_protocols_return_validated_structured_output_and_usage():
    responses_api = ResponsesApi()
    responses = OpenAIResponsesAdapter(
        client=SimpleNamespace(responses=responses_api),
        model="response-model",
    )
    chat_api = ChatCompletionsApi()
    chat = OpenAIChatCompletionsAdapter(
        client=SimpleNamespace(
            chat=SimpleNamespace(completions=chat_api),
        ),
        model="chat-model",
    )

    response_result = responses.parse_structured(
        instructions="Return strict output.",
        input_text="input",
        response_model=StrictExample,
    )
    chat_result = chat.parse_structured(
        instructions="Return strict output.",
        input_text="input",
        response_model=StrictExample,
    )

    assert response_result.output == StrictExample(value="ok")
    assert response_result.model == "resolved-responses-model"
    assert response_result.usage == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }
    assert chat_result.output == StrictExample(value="ok")
    assert chat_result.model == "resolved-chat-model"
    assert chat_result.usage["total_tokens"] == 18


def test_factory_uses_explicit_protocol_without_auto_detection():
    client = SimpleNamespace()

    responses = create_model_gateway(
        ModelConnection(protocol="responses", model="responses-model"),
        api_key="secret",
        client=client,
    )
    chat = create_model_gateway(
        ModelConnection(protocol="chat_completions", model="chat-model"),
        api_key="secret",
        client=client,
    )

    assert isinstance(responses, OpenAIResponsesAdapter)
    assert isinstance(chat, OpenAIChatCompletionsAdapter)


def test_deployment_gateway_requires_explicit_enablement():
    """The deployment-level demo path stays off unless explicitly enabled."""
    settings = Settings(llm_enabled=False, openai_api_key="sk-test")

    assert build_model_gateway(settings=settings) is None


def test_deployment_gateway_requires_an_api_key():
    settings = Settings(llm_enabled=True, openai_api_key=None)

    assert build_model_gateway(settings=settings) is None


def test_responses_adapter_sends_the_configured_model_and_route_schema():
    """The request must carry the configured model and the PlannerRoute schema."""
    responses = ResponsesApi()
    adapter = OpenAIResponsesAdapter(client=SimpleNamespace(responses=responses), model="test-model")

    adapter.plan_route("question")

    assert responses.parse_calls[0]["model"] == "test-model"
    assert responses.parse_calls[0]["text_format"] is PlannerRoute


def test_responses_adapter_prompts_identify_the_agent_and_ask_for_markdown():
    responses = ResponsesApi()
    adapter = OpenAIResponsesAdapter(client=SimpleNamespace(responses=responses), model="test-model")

    adapter.plan_route("question")
    adapter.write_answer({"user_query": "question", "tool_results": {"meal": "meal_templates.md"}})

    assert "FitLife Coach Agent" in responses.parse_calls[0]["instructions"]
    assert "Markdown" in responses.create_calls[-1]["instructions"]


def test_responses_adapter_rejects_a_response_without_a_structured_route():
    responses = MissingStructuredRouteResponses()
    adapter = OpenAIResponsesAdapter(client=SimpleNamespace(responses=responses), model="test-model")

    with pytest.raises(ValueError, match="structured output"):
        adapter.plan_route("question")


def test_responses_adapter_rejects_a_blank_answer():
    responses = BlankAnswerResponses()
    adapter = OpenAIResponsesAdapter(client=SimpleNamespace(responses=responses), model="test-model")

    with pytest.raises(ValueError, match="text"):
        adapter.write_answer({"user_query": "question"})
