import pandas as pd
import pytest

from backend.agent import graph as agent_graph
from backend.agent.graph import run_contextual_coach_action, run_fitlife_agent
from backend.agent.planner import PlannerRoute
from backend.config import Settings
from backend.domain.errors import ApplicationError
from backend.domain.model_connection import ModelConnection
from backend.infrastructure.model_gateway.factory import resolve_user_model_gateway
from backend.infrastructure.repositories.file_fitness_repository import FileFitnessRepository
from backend.tools.data_access import DEFAULT_PROFILE, MEAL_COLUMNS, WORKOUT_COLUMNS


class FakeGateway:
    model = "fake-model"

    def __init__(self, answer: str = "## Model answer") -> None:
        self.answer = answer

    def plan_route(self, question: str) -> PlannerRoute:
        return PlannerRoute(intent="knowledge_qa")

    def write_answer(self, state: dict) -> str:
        return self.answer


class ModelConnectionRepository:
    def __init__(self, connection: ModelConnection | None) -> None:
        self.connection = connection

    def get(self, user_id: str) -> ModelConnection | None:
        return self.connection

    def save(self, user_id: str, connection: ModelConnection) -> None:
        self.connection = connection


class UserCipher:
    def encrypt(self, plaintext: str) -> str:
        return f"encrypted:{plaintext}"

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext.removeprefix("encrypted:")


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


def test_authenticated_agent_uses_user_gateway_without_deployment_fallback(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        agent_graph,
        "resolve_user_model_gateway",
        lambda user_id: (calls.append(user_id), FakeGateway())[1],
    )
    monkeypatch.setattr(
        agent_graph,
        "build_model_gateway",
        lambda: (_ for _ in ()).throw(AssertionError("deployment gateway must be ignored")),
    )

    result = run_fitlife_agent("Help me understand today", user_id="user-a")

    assert result["model"] == "fake-model"
    assert calls == ["user-a"]


def test_user_gateway_resolver_uses_only_enabled_user_credentials():
    connection = ModelConnection(
        model="user-model",
        encrypted_api_key="encrypted:user-secret",
        enabled=True,
    )
    captured: list[tuple[str, str]] = []
    settings = Settings(llm_enabled=True, openai_api_key="deployment-secret")

    gateway = resolve_user_model_gateway(
        "user-a",
        repository=ModelConnectionRepository(connection),
        cipher=UserCipher(),
        settings=settings,
        gateway_factory=lambda stored, api_key: (
            captured.append((stored.model, api_key)),
            FakeGateway(),
        )[1],
    )

    assert gateway.model == "fake-model"
    assert captured == [("user-model", "user-secret")]


def test_user_gateway_resolver_rejects_disabled_connection():
    connection = ModelConnection(
        encrypted_api_key="encrypted:user-secret",
        enabled=False,
    )

    with pytest.raises(ApplicationError) as raised:
        resolve_user_model_gateway(
            "user-a",
            repository=ModelConnectionRepository(connection),
            cipher=UserCipher(),
        )

    assert raised.value.code == "AI_DISABLED"


def test_user_gateway_resolver_reports_unavailable_credential_store():
    connection = ModelConnection(
        encrypted_api_key="encrypted:user-secret",
        enabled=True,
    )

    with pytest.raises(ApplicationError) as raised:
        resolve_user_model_gateway(
            "user-a",
            repository=ModelConnectionRepository(connection),
            cipher=None,
            settings=Settings(settings_encryption_key=None),
        )

    assert raised.value.code == "CREDENTIAL_STORE_UNAVAILABLE"


def test_user_gateway_resolver_reports_credentials_that_cannot_be_decrypted():
    class BrokenCipher(UserCipher):
        def decrypt(self, ciphertext: str) -> str:
            raise ValueError("ciphertext details must not escape")

    connection = ModelConnection(
        encrypted_api_key="unreadable-ciphertext",
        enabled=True,
    )

    with pytest.raises(ApplicationError) as raised:
        resolve_user_model_gateway(
            "user-a",
            repository=ModelConnectionRepository(connection),
            cipher=BrokenCipher(),
        )

    assert raised.value.code == "CREDENTIAL_STORE_UNAVAILABLE"
    assert "ciphertext details" not in raised.value.message


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


def test_contextual_coach_receives_selected_day_deterministic_context():
    class SelectedDayRepository:
        def read_profile(self, user_id=None):
            return DEFAULT_PROFILE.model_copy()

        def read_meals(self, user_id=None):
            return pd.DataFrame(
                [
                    {
                        "date": "2026-07-09",
                        "meal": "lunch",
                        "food": "beef rice",
                        "amount": "1 bowl",
                        "calories": 620,
                        "protein": 38,
                        "carbs": 72,
                        "fat": 16,
                    }
                ],
                columns=MEAL_COLUMNS,
            )

        def read_workouts(self, user_id=None):
            return pd.DataFrame(columns=WORKOUT_COLUMNS)

    class CapturingGateway(FakeGateway):
        captured_state: dict | None = None

        def write_answer(self, state: dict) -> str:
            self.captured_state = state
            return "## Selected day interpretation"

    gateway = CapturingGateway()
    result = run_contextual_coach_action(
        surface="today",
        action="explain_today",
        date="2026-07-09",
        repository=SelectedDayRepository(),
        gateway=gateway,
    )

    assert gateway.captured_state is not None
    overview = gateway.captured_state["tool_results"]["today_overview"]
    assert overview["date"] == "2026-07-09"
    assert overview["summary"]["calories"] == 620
    assert "build_today_overview" in result["trace"]["tool_calls"]
