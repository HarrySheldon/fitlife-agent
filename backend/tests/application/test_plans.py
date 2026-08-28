from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import backend.agent.graph as agent_graph
from backend.api import plan as plan_api
from backend.agent.planner import PlannerRoute
from backend.api.plan import generate_adjusted_plan
from backend.api.dependencies import require_current_user
from backend.application.ports.plan_repository import StoredPlan
from backend.application.ports.structured_model_gateway import StructuredModelResult
from backend.application.use_cases.plans import Plans
from backend.domain.errors import ApplicationError
from backend.infrastructure.repositories.file_plan_repository import FilePlanRepository
from backend.infrastructure.user_lifecycle import user_lifecycle_guard
from backend.schemas import AuthenticatedUser
from backend.tools.data_access import DEFAULT_PROFILE, MEAL_COLUMNS, WORKOUT_COLUMNS


VALID_PLAN = {
    "diet_plan": {"daily_calorie_target": 2200},
    "workout_plan": {"weekly_training_days": 4},
    "validation": {"passed": True, "warnings": [], "violations": [], "repair_suggestions": []},
    "trace": {"tool_calls": ["generate_next_week_plan"]},
}


def test_deterministic_generation_returns_a_validated_draft_without_persisting(tmp_path):
    repository = FilePlanRepository(tmp_path)
    validation_calls: list[dict] = []

    def validate(user_id: str, plan: dict) -> dict:
        validation_calls.append(plan)
        return VALID_PLAN["validation"]

    plans = Plans(
        repository,
        generate_deterministic=lambda user_id: VALID_PLAN,
        generate_adjusted=lambda user_id, active, instructions: VALID_PLAN,
        validate_plan=validate,
        now=lambda: datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc),
        new_id=lambda: "plan-00000001",
        new_draft_id=lambda: "draft-0000000000000001",
    )

    draft = plans.draft("user-a")

    assert draft.kind == "deterministic"
    assert draft.plan.validation.passed is True
    assert len(validation_calls) == 1
    assert repository.list("user-a") == []
    assert repository.get_draft("user-a", draft.draft_id) == draft


def test_invalid_draft_cannot_be_activated(tmp_path):
    invalid = {
        **VALID_PLAN,
        "validation": {
            "passed": False,
            "warnings": [],
            "violations": ["unsafe volume"],
            "repair_suggestions": ["reduce volume"],
        },
    }
    repository = FilePlanRepository(tmp_path)
    plans = Plans(
        repository,
        generate_deterministic=lambda user_id: invalid,
        generate_adjusted=lambda user_id, active, instructions: invalid,
        validate_plan=lambda user_id, plan: invalid["validation"],
        new_draft_id=lambda: "draft-0000000000000001",
    )
    draft = plans.draft("user-a")

    with pytest.raises(ApplicationError) as error:
        plans.activate("user-a", draft.draft_id)

    assert error.value.code == "PLAN_DRAFT_INVALID"
    assert repository.list("user-a") == []


def test_explicit_confirmation_creates_a_per_user_plan_id_and_isolates_list_and_detail(tmp_path):
    repository = FilePlanRepository(tmp_path)
    ids = iter(["plan-00000001", "plan-00000002"])
    plans = Plans(
        repository,
        generate_deterministic=lambda user_id: VALID_PLAN,
        generate_adjusted=lambda user_id, active, instructions: VALID_PLAN,
        validate_plan=lambda user_id, plan: VALID_PLAN["validation"],
        now=lambda: datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc),
        new_id=lambda: next(ids),
        new_draft_id=iter(["draft-0000000000000001", "draft-0000000000000002"]).__next__,
    )

    user_a_draft = plans.draft("user-a")
    user_b_draft = plans.draft("user-b")
    user_a = plans.activate("user-a", user_a_draft.draft_id)
    user_b = plans.activate("user-b", user_b_draft.draft_id)

    assert user_a.plan_id == "plan-00000001"
    assert user_b.plan_id == "plan-00000002"
    assert plans.list("user-a") == [user_a]
    assert plans.get("user-a", user_a.plan_id) == user_a
    with pytest.raises(ApplicationError) as error:
        plans.get("user-b", user_a.plan_id)
    assert error.value.code == "PLAN_NOT_FOUND"


def test_agent_adjustment_returns_a_revalidated_draft_and_never_persists_before_confirmation(tmp_path):
    repository = FilePlanRepository(tmp_path)
    adjusted = {**VALID_PLAN, "trace": {"tool_calls": ["agent_adjust_plan"]}}
    calls: list[tuple[str, str, str]] = []

    def generate_adjusted(user_id, active, instructions):
        calls.append((user_id, active.plan_id, instructions))
        return adjusted

    plans = Plans(
        repository,
        generate_deterministic=lambda user_id: VALID_PLAN,
        generate_adjusted=generate_adjusted,
        validate_plan=lambda user_id, plan: VALID_PLAN["validation"],
        now=lambda: datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc),
        new_id=iter(["plan-00000001", "plan-00000002"]).__next__,
        new_draft_id=iter(["draft-0000000000000001", "draft-0000000000000002"]).__next__,
    )
    initial = plans.draft("user-a")
    active = plans.activate("user-a", initial.draft_id)

    draft = plans.adjustment_draft("user-a", active.plan_id, "Make Friday lighter")

    assert draft.kind == "agent_adjusted"
    assert draft.based_on_plan_id == active.plan_id
    assert draft.plan.validation.passed is True
    assert calls == [("user-a", active.plan_id, "Make Friday lighter")]
    assert plans.list("user-a") == [active]
    adjusted_active = plans.activate("user-a", draft.draft_id)
    assert adjusted_active.kind == "agent_adjusted"
    assert adjusted_active.based_on_plan_id == active.plan_id


@pytest.mark.parametrize("plan_id", ["plan-short", "../plan-00000001", "plan-0000000G"])
def test_plan_ids_are_strictly_validated(tmp_path, plan_id):
    with pytest.raises(ValueError, match="Invalid plan id"):
        FilePlanRepository(tmp_path).get("user-a", plan_id)


def test_corrupt_stored_plan_raises_a_controlled_error(tmp_path):
    path = tmp_path / "users" / "user-a" / "plans" / "plan-00000001.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ApplicationError) as error:
        FilePlanRepository(tmp_path).get("user-a", "plan-00000001")

    assert error.value.code == "PLAN_STORAGE_INVALID"


def test_plan_reads_are_blocked_after_user_deletion(tmp_path):
    repository = FilePlanRepository(tmp_path)
    plans = Plans(
        repository,
        generate_deterministic=lambda user_id: VALID_PLAN,
        generate_adjusted=lambda user_id, active, instructions: VALID_PLAN,
        validate_plan=lambda user_id, plan: VALID_PLAN["validation"],
        new_id=lambda: "plan-00000001",
        new_draft_id=lambda: "draft-0000000000000001",
    )
    draft = plans.draft("deleted-user")
    plans.activate("deleted-user", draft.draft_id)
    with user_lifecycle_guard(tmp_path, "deleted-user") as lifecycle:
        lifecycle.mark_deleted()

    with pytest.raises(ApplicationError) as error:
        plans.list("deleted-user")
    assert error.value.code == "AUTH_TOKEN_INVALID"


def test_plan_endpoints_keep_draft_and_activation_explicit(tmp_path, monkeypatch):
    service = Plans(
        FilePlanRepository(tmp_path),
        generate_deterministic=lambda user_id: VALID_PLAN,
        generate_adjusted=lambda user_id, active, instructions: VALID_PLAN,
        validate_plan=lambda user_id, plan: VALID_PLAN["validation"],
        now=lambda: datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc),
        new_id=lambda: "plan-00000001",
        new_draft_id=iter(["draft-0000000000000001", "draft-0000000000000002"]).__next__,
    )
    monkeypatch.setattr(plan_api, "_plans", lambda: service)
    app = FastAPI()
    app.include_router(plan_api.router)
    app.dependency_overrides[require_current_user] = lambda: AuthenticatedUser(
        user_id="user-a", display_name="User A"
    )
    client = TestClient(app)

    draft_response = client.post("/plan/draft")
    assert draft_response.status_code == 200
    draft_payload = draft_response.json()
    assert draft_payload["processing_mode"] == "deterministic"
    assert client.get("/plan").json()["data"] == []

    activated = client.post("/plan/activate", json={"draft_id": draft_payload["data"]["draft_id"]}).json()["data"]
    assert activated["plan_id"] == "plan-00000001"
    assert client.get("/plan").json()["data"] == [activated]
    assert client.get("/plan/plan-00000001").json()["data"] == activated

    adjusted = client.post(
        "/plan/plan-00000001/draft", json={"instructions": "Make Friday lighter"}
    ).json()
    assert adjusted["processing_mode"] == "agent"
    assert adjusted["data"]["kind"] == "agent_adjusted"
    assert len(client.get("/plan").json()["data"]) == 1


def test_plan_interpretation_endpoint_loads_the_authorized_persisted_plan(tmp_path, monkeypatch):
    service = Plans(
        FilePlanRepository(tmp_path),
        generate_deterministic=lambda user_id: VALID_PLAN,
        generate_adjusted=lambda user_id, active, instructions: VALID_PLAN,
        validate_plan=lambda user_id, plan: VALID_PLAN["validation"],
        new_id=lambda: "plan-00000001",
        new_draft_id=lambda: "draft-0000000000000001",
    )
    service.activate("user-a", service.draft("user-a").draft_id)
    captured: dict = {}

    def interpret(**kwargs):
        captured.update(kwargs)
        return {
            "answer_markdown": "Persisted plan interpretation",
            "intent": "plan_adjustment",
            "trace": {"active_plan_id": kwargs["plan_id"]},
            "sources": [],
            "model": "test-model",
            "request_id": "request-1",
        }

    monkeypatch.setattr(plan_api, "_plans", lambda: service)
    monkeypatch.setattr(plan_api, "interpret_persisted_plan", interpret)
    monkeypatch.setattr(plan_api, "preferences_for", lambda user: object())
    app = FastAPI()
    app.include_router(plan_api.router)
    app.dependency_overrides[require_current_user] = lambda: AuthenticatedUser(
        user_id="user-a", display_name="User A"
    )

    response = TestClient(app).post("/plan/plan-00000001/interpret")

    assert response.status_code == 200
    assert response.json()["data"]["answer_markdown"] == "Persisted plan interpretation"
    assert captured["plan_id"] == "plan-00000001"
    assert captured["plan"] == VALID_PLAN
    assert captured["user_id"] == "user-a"


def test_malformed_plan_id_is_a_controlled_not_found_error(tmp_path, monkeypatch):
    plans = Plans(
        FilePlanRepository(tmp_path),
        generate_deterministic=lambda user_id: VALID_PLAN,
        generate_adjusted=lambda user_id, active, instructions: VALID_PLAN,
        validate_plan=lambda user_id, plan: VALID_PLAN["validation"],
    )

    with pytest.raises(ApplicationError) as error:
        plans.get("user-a", "../../other-user")

    assert error.value.code == "PLAN_NOT_FOUND"
    assert error.value.status_code == 404

    app = FastAPI()

    @app.exception_handler(ApplicationError)
    async def handle_application_error(_request: Request, cause: ApplicationError):
        return JSONResponse(
            status_code=cause.status_code,
            content={"error": {"code": cause.code, "message": cause.message}},
        )

    app.include_router(plan_api.router)
    app.dependency_overrides[require_current_user] = lambda: AuthenticatedUser(
        user_id="user-a", display_name="User A"
    )
    monkeypatch.setattr(plan_api, "_plans", lambda: plans)
    response = TestClient(app).get("/plan/not-a-plan-id")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PLAN_NOT_FOUND"


def test_persisted_plan_interpretation_supplies_the_plan_of_record(monkeypatch):
    captured: dict = {}

    def run_agent(prompt, user_id, **kwargs):
        captured.update({"prompt": prompt, "user_id": user_id, **kwargs})
        return {
            "answer_markdown": "Use this plan",
            "intent": "plan_adjustment",
            "trace": {"tool_calls": kwargs["initial_tool_calls"]},
            "sources": [],
            "model": "test-model",
            "request_id": "request-1",
        }

    monkeypatch.setattr(agent_graph, "run_fitlife_agent", run_agent)
    result = agent_graph.interpret_persisted_plan(
        plan_id="plan-00000001",
        plan=VALID_PLAN,
        user_id="user-a",
    )

    assert captured["initial_tool_results"] == {
        "active_plan_id": "plan-00000001",
        "active_plan": VALID_PLAN,
    }
    assert captured["initial_tool_calls"] == ["load_persisted_plan"]
    assert "do not generate" in captured["prompt"]
    assert result["trace"]["active_plan_id"] == "plan-00000001"


def test_persisted_plan_interpretation_never_generates_a_substitute_plan():
    class Repository:
        def read_profile(self, user_id=None):
            return DEFAULT_PROFILE.model_copy()

        def read_meals(self, user_id=None):
            return pd.DataFrame(columns=MEAL_COLUMNS)

        def read_workouts(self, user_id=None):
            return pd.DataFrame(columns=WORKOUT_COLUMNS)

    class Gateway:
        model = "test-model"
        captured_state = None

        def plan_route(self, question):
            return PlannerRoute(intent="plan_generation", needs_plan=True)

        def write_answer(self, state):
            self.captured_state = state
            return "Advice for the persisted plan"

    gateway = Gateway()
    result = agent_graph.interpret_persisted_plan(
        plan_id="plan-00000001",
        plan=VALID_PLAN,
        user_id="user-a",
        repository=Repository(),
        gateway=gateway,
    )

    assert gateway.captured_state["tool_results"]["active_plan"] == VALID_PLAN
    assert "generated_plan" not in gateway.captured_state["tool_results"]
    assert "load_persisted_plan" in result["trace"]["tool_calls"]
    assert "generate_next_week_plan" not in result["trace"]["tool_calls"]


def test_activation_restores_consumed_draft_when_plan_storage_fails(tmp_path):
    class FailingRepository(FilePlanRepository):
        fail_save = True

        def save(self, user_id, plan):
            if self.fail_save:
                raise OSError("storage unavailable")
            return super().save(user_id, plan)

    repository = FailingRepository(tmp_path)
    plans = Plans(
        repository,
        generate_deterministic=lambda user_id: VALID_PLAN,
        generate_adjusted=lambda user_id, active, instructions: VALID_PLAN,
        validate_plan=lambda user_id, plan: VALID_PLAN["validation"],
        new_id=lambda: "plan-00000001",
        new_draft_id=lambda: "draft-0000000000000001",
    )
    draft = plans.draft("user-a")

    with pytest.raises(OSError, match="storage unavailable"):
        plans.activate("user-a", draft.draft_id)

    assert repository.get_draft("user-a", draft.draft_id) == draft
    repository.fail_save = False
    assert plans.activate("user-a", draft.draft_id).plan_id == "plan-00000001"


def test_draft_activation_is_per_user_one_time_and_rejects_missing_ids(tmp_path):
    plans = Plans(
        FilePlanRepository(tmp_path),
        generate_deterministic=lambda user_id: VALID_PLAN,
        generate_adjusted=lambda user_id, active, instructions: VALID_PLAN,
        validate_plan=lambda user_id, plan: VALID_PLAN["validation"],
        new_id=lambda: "plan-00000001",
        new_draft_id=lambda: "draft-0000000000000001",
    )
    draft = plans.draft("user-a")

    for user_id in ("user-b",):
        with pytest.raises(ApplicationError) as error:
            plans.activate(user_id, draft.draft_id)
        assert error.value.code == "PLAN_DRAFT_NOT_FOUND"

    plans.activate("user-a", draft.draft_id)
    with pytest.raises(ApplicationError) as error:
        plans.activate("user-a", draft.draft_id)
    assert error.value.code == "PLAN_DRAFT_NOT_FOUND"


def test_expired_opaque_draft_cannot_activate(tmp_path):
    clock = iter([
        datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 26, 10, 31, tzinfo=timezone.utc),
    ])
    plans = Plans(
        FilePlanRepository(tmp_path),
        generate_deterministic=lambda user_id: VALID_PLAN,
        generate_adjusted=lambda user_id, active, instructions: VALID_PLAN,
        validate_plan=lambda user_id, plan: VALID_PLAN["validation"],
        now=clock.__next__,
        new_draft_id=lambda: "draft-0000000000000001",
        draft_ttl=timedelta(minutes=30),
    )
    draft = plans.draft("user-a")

    with pytest.raises(ApplicationError) as error:
        plans.activate("user-a", draft.draft_id)

    assert error.value.code == "PLAN_DRAFT_EXPIRED"
    assert plans.list("user-a") == []


def test_activate_endpoint_rejects_client_source_metadata(tmp_path, monkeypatch):
    service = Plans(
        FilePlanRepository(tmp_path),
        generate_deterministic=lambda user_id: VALID_PLAN,
        generate_adjusted=lambda user_id, active, instructions: VALID_PLAN,
        validate_plan=lambda user_id, plan: VALID_PLAN["validation"],
        new_draft_id=lambda: "draft-0000000000000001",
    )
    draft = service.draft("user-a")
    monkeypatch.setattr(plan_api, "_plans", lambda: service)
    app = FastAPI()
    app.include_router(plan_api.router)
    app.dependency_overrides[require_current_user] = lambda: AuthenticatedUser(user_id="user-a", display_name="A")

    response = TestClient(app).post(
        "/plan/activate",
        json={"draft_id": draft.draft_id, "kind": "agent_adjusted", "based_on_plan_id": "plan-deadbeef"},
    )

    assert response.status_code == 422
    assert service.list("user-a") == []


def test_agent_adjustment_context_changes_with_the_full_active_plan():
    captured: list[dict] = []

    class Gateway:
        model = "fake-agent"

        def parse_structured(self, *, instructions, input_text, response_model):
            context = __import__("json").loads(input_text)
            captured.append(context)
            output = {
                **context["active_plan"],
                "diet_plan": {**context["active_plan"]["diet_plan"], "marker": context["active_plan_id"]},
            }
            return StructuredModelResult(
                output=response_model.model_validate(output), model=self.model, usage={"input_tokens": 1}
            )

    def active(plan_id: str, calories: int) -> StoredPlan:
        plan = {**VALID_PLAN, "diet_plan": {"daily_calorie_target": calories}}
        return StoredPlan(
            plan_id=plan_id,
            activated_at=datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc),
            kind="deterministic",
            plan=plan,
        )

    first = generate_adjusted_plan("user-a", active("plan-00000001", 1800), "lighter", gateway=Gateway())
    second = generate_adjusted_plan("user-a", active("plan-00000002", 2400), "lighter", gateway=Gateway())

    assert captured[0]["active_plan_id"] == "plan-00000001"
    assert captured[0]["active_plan"]["diet_plan"]["daily_calorie_target"] == 1800
    assert captured[0]["adjustment_instructions"] == "lighter"
    assert captured[1]["active_plan_id"] == "plan-00000002"
    assert captured[1]["active_plan"]["diet_plan"]["daily_calorie_target"] == 2400
    assert first["diet_plan"] != second["diet_plan"]
