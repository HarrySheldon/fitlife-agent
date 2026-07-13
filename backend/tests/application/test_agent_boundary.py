import pytest

from backend.agent.graph import run_contextual_coach_action, run_fitlife_agent
from backend.agent.planner import PlannerRoute
from backend.domain.errors import ApplicationError
from backend.infrastructure.repositories.file_fitness_repository import FileFitnessRepository


class FakeGateway:
    model = "fake-model"

    def __init__(self, answer: str = "## Model answer") -> None:
        self.answer = answer

    def plan_route(self, question: str) -> PlannerRoute:
        return PlannerRoute(intent="knowledge_qa")

    def write_answer(self, state: dict) -> str:
        return self.answer


def test_agent_uses_injected_gateway_and_reports_model_metadata():
    result = run_fitlife_agent(
        "Help me understand today",
        repository=FileFitnessRepository(),
        gateway=FakeGateway(),
    )

    assert result["answer_markdown"] == "## Model answer"
    assert result["model"] == "fake-model"
    assert result["request_id"]
    assert result["trace"]["llm_answer_used"] is True


def test_agent_normalizes_model_timeout_without_template_fallback():
    class TimeoutGateway(FakeGateway):
        def write_answer(self, state: dict) -> str:
            raise TimeoutError("provider details must not escape")

    with pytest.raises(ApplicationError) as raised:
        run_fitlife_agent(
            "Help me understand today",
            repository=FileFitnessRepository(),
            gateway=TimeoutGateway(),
        )

    assert raised.value.code == "MODEL_TIMEOUT"
    assert "provider details" not in raised.value.message


def test_agent_does_not_fallback_when_model_planning_fails():
    class BrokenPlannerGateway(FakeGateway):
        def plan_route(self, question: str) -> PlannerRoute:
            raise RuntimeError("provider response body")

    with pytest.raises(ApplicationError) as raised:
        run_fitlife_agent(
            "Create a weekly report",
            repository=FileFitnessRepository(),
            gateway=BrokenPlannerGateway(),
        )

    assert raised.value.code == "MODEL_PROTOCOL_ERROR"


def test_contextual_coach_keeps_model_answer_instead_of_replacing_it():
    result = run_contextual_coach_action(
        surface="today",
        action="explain_today",
        date="2026-07-09",
        user_id=None,
        repository=FileFitnessRepository(),
        gateway=FakeGateway("## Personalized interpretation"),
    )

    assert result["answer_markdown"] == "## Personalized interpretation"
    assert result["trace"]["coach_action"] == "explain_today"
