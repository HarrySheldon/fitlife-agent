from __future__ import annotations

from types import SimpleNamespace

from backend.agent.llm_adapter import (
    OpenAIResponsesAdapter,
    build_llm_adapter,
    try_plan_route_with_llm,
    try_write_answer_with_llm,
)
from backend.agent.planner import PlannerRoute
from backend.config import Settings


class FakeResponses:
    def __init__(self, *, parsed_route: PlannerRoute | None = None, output_text: str = ""):
        self.parsed_route = parsed_route
        self.output_text = output_text
        self.parse_calls: list[dict] = []
        self.create_calls: list[dict] = []

    def parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        return SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="message",
                    content=[
                        SimpleNamespace(
                            type="output_text",
                            parsed=self.parsed_route,
                        )
                    ],
                )
            ]
        )

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


class FakeClient:
    def __init__(self, responses: FakeResponses):
        self.responses = responses


def test_build_llm_adapter_requires_explicit_enablement():
    settings = Settings(llm_enabled=False, openai_api_key="sk-test")

    assert build_llm_adapter(settings=settings) is None


def test_build_llm_adapter_requires_api_key():
    settings = Settings(llm_enabled=True, openai_api_key=None)

    assert build_llm_adapter(settings=settings) is None


def test_openai_responses_adapter_parses_planner_route_with_structured_output():
    responses = FakeResponses(
        parsed_route=PlannerRoute(
            intent="plan_generation",
            needs_workout_analysis=True,
            needs_retrieval=True,
            needs_plan=True,
        )
    )
    adapter = OpenAIResponsesAdapter(client=FakeClient(responses), model="test-model")

    route = adapter.plan_route("Create a workout plan for next week.")

    assert route == PlannerRoute(
        intent="plan_generation",
        needs_workout_analysis=True,
        needs_retrieval=True,
        needs_plan=True,
    )
    assert responses.parse_calls[0]["model"] == "test-model"
    assert responses.parse_calls[0]["text_format"] is PlannerRoute
    assert "FitLife Coach Agent" in responses.parse_calls[0]["instructions"]


def test_openai_responses_adapter_writes_answer_with_responses_create():
    responses = FakeResponses(output_text="## LLM Answer\nUse the retrieved guidance.")
    adapter = OpenAIResponsesAdapter(client=FakeClient(responses), model="test-model")

    answer = adapter.write_answer(
        {
            "user_query": "What can replace chicken breast?",
            "intent": "knowledge_qa",
            "tool_results": {},
            "retrieved_docs": [{"source": "meal_templates.md", "text": "fish, tofu"}],
            "validation_result": {"passed": True, "warnings": []},
        }
    )

    assert answer == "## LLM Answer\nUse the retrieved guidance."
    assert responses.create_calls[0]["model"] == "test-model"
    assert "Markdown" in responses.create_calls[0]["instructions"]
    assert "meal_templates.md" in responses.create_calls[0]["input"]


def test_try_plan_route_with_llm_returns_none_when_adapter_fails():
    class BrokenAdapter:
        def plan_route(self, question: str):
            raise RuntimeError("provider failed")

    assert try_plan_route_with_llm("Create a plan", adapter=BrokenAdapter()) is None


def test_try_write_answer_with_llm_returns_none_for_blank_output():
    responses = FakeResponses(output_text="   ")
    adapter = OpenAIResponsesAdapter(client=FakeClient(responses), model="test-model")

    assert try_write_answer_with_llm({"user_query": "hello"}, adapter=adapter) is None
