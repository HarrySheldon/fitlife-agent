from types import SimpleNamespace

from backend.agent.planner import PlannerRoute
from backend.domain.model_connection import ModelConnection
from backend.infrastructure.model_gateway.factory import create_model_gateway
from backend.infrastructure.model_gateway.openai_chat_completions import OpenAIChatCompletionsAdapter
from backend.infrastructure.model_gateway.openai_responses import OpenAIResponsesAdapter


class ResponsesApi:
    def __init__(self) -> None:
        self.create_calls: list[dict] = []

    def parse(self, **kwargs):
        route = PlannerRoute(intent="knowledge_qa")
        content = SimpleNamespace(type="output_text", parsed=route)
        return SimpleNamespace(output=[SimpleNamespace(type="message", content=[content])])

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
        message = SimpleNamespace(parsed=PlannerRoute(intent="knowledge_qa"), content=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

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
