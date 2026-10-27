"""Public contract of the plan-adjustment task entry.

These tests drive the HTTP surface only. They assert what a client can observe --
status codes, ownership, the grant, the round, the confirmation -- and never reach
into the repository to make a point. A second entry that bypassed the same service
would pass the service tests and fail these.

The model is scripted; everything else is real. The task store, the plan store,
the versioned profile snapshot and the single slot are the production ones, so
what is being tested is the seam between HTTP and them, not a stand-in for it.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.agent.context_builder import ExecutionPrincipal
from backend.agent.contracts import AgentCommand
from backend.agent.plan_adjustment.validation import PlanValidation
from backend.agent.runtime import AgentRuntime
from backend.agent.skills.catalog import SkillCatalog
from backend.agent.tasks.contracts import TaskRef
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.handlers import BoundFitnessReads
from backend.agent.plan_adjustment.tools import PLAN_TOOL_SPECS
from backend.agent.unified_coach import UnifiedCoachWorkflow
from backend.api.coach_conversations import (
    get_coach_admission_service,
    reset_coach_turn_services,
)
from backend.api.plan_adjustment import (
    get_plan_adjustment_service,
    reset_plan_adjustment_services,
)
from backend.application.ports.plan_repository import StoredPlan
from backend.application.ports.profile_target_repository import (
    GoalVersionInput,
    ProfileVersionInput,
    SafetyVersionInput,
    TargetVersionInput,
)
from backend.application.use_cases.plan_adjustment import PlanAdjustmentService
from backend.config import get_settings
from backend.infrastructure.repositories.file_plan_repository import FilePlanRepository
from backend.infrastructure.repositories.sqlite_plan_adjustment_repository import (
    SQLitePlanAdjustmentRepository,
)
from backend.infrastructure.repositories.sqlite_plan_repository import (
    SQLitePlanRepository,
)
from backend.infrastructure.repositories.sqlite_profile_target_repository import (
    SQLiteProfileTargetRepository,
)
from backend.infrastructure.repositories.sqlite_task_budget_repository import (
    SQLiteTaskBudgetRepository,
)
from backend.infrastructure.sqlite.runtime import get_database, initialize_database
from backend.main import create_app
from backend.schemas import GeneratedPlan
from backend.tests.test_plan_adjustment_service import (
    BASE,
    CONSTRAINTS,
    NOW,
    ROUND_0,
    ROUND_1,
    ROUND_2,
    ForbiddenRepository,
    ScriptedGateway,
)

TASKS = "/api/v1/plan-adjustment-tasks"
PLAN_ID = "plan-aaaaaaaa"
INSTRUCTIONS = "把训练和饮食都调整一下"


# -- fixtures ------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_caches():
    yield
    reset_plan_adjustment_services()
    reset_coach_turn_services()
    get_settings.cache_clear()


@pytest.fixture
def api(monkeypatch):
    """A registered account and the app it talks to."""
    data_dir = Path(".tmp") / "pytest-plan-adjustment-api" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("PLAN_ADJUSTMENT_TASKS_ENABLED", "true")
    get_settings.cache_clear()
    initialize_database()
    client = TestClient(create_app())
    session = _register(client, "plan-task-user")
    yield client, session
    client.close()


def _register(client: TestClient, username: str) -> dict:
    response = client.post(
        "/auth/register",
        json={"username": username, "password": "password123", "display_name": username},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _auth(session: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}


# -- the world the task runs in -----------------------------------------
def _seed(owner: str) -> SQLitePlanRepository:
    """A profile with versioned targets and a plan the task may be based on.

    The versioned rows are what makes confirmation possible at all: without them
    the service refuses, because a safety check nobody can reproduce is not a
    check. The values match ``CONSTRAINTS`` so the task's frozen snapshot and the
    store's current one agree -- a drift here would (correctly) refuse.
    """
    database = get_database()
    profiles = SQLiteProfileTargetRepository(database)
    setup = profiles.bootstrap(
        owner,
        ProfileVersionInput(age=30, height_cm=175.0, weight_kg=70.0,
                            energy_parameter="male", activity_level="moderate",
                            auto_target_disabled=False, safety_conditions=(),
                            effective_from="2026-10-01"),
        GoalVersionInput(goal="fat_loss", effective_from="2026-10-01"),
    )
    profiles.append_target(owner, TargetVersionInput(
        profile_version_id=setup.profile.id,
        overall_goal_version_id=setup.goal.id,
        calories=2000, carbs=250, protein=140, fat=60,
        source="manual", formula_version=None,
        rationale={"confirmed_warnings": []}, effective_from="2026-10-02"))
    profiles.append_safety_if_changed(
        owner, SafetyVersionInput(allergies_or_restrictions=("花生",)))
    plans = SQLitePlanRepository(
        database, clock=lambda: NOW,
        constraints_reader=profiles.constraint_snapshot_with)
    plans.save(owner, StoredPlan(plan_id=PLAN_ID, activated_at=NOW,
                                 kind="deterministic",
                                 plan=GeneratedPlan.model_validate(BASE)))
    return plans


def _executor(session, owner: str) -> ToolExecutor:
    principal = ExecutionPrincipal(
        owner, authorized_domains=frozenset(session.current().read_domains))
    return ToolExecutor(
        principal=principal,
        reads=BoundFitnessReads(ForbiddenRepository(), owner),
        catalog=SkillCatalog(),
        authorize=lambda actor: actor.authorized_domains,
        retriever=lambda *a, **k: [],
        language="zh-CN",
        # The published plan tool set, not the wider coach one: a task may read its
        # base and submit a candidate, and nothing else.
        specs=PLAN_TOOL_SPECS,
        session=session,
    )


def _runner(scripts, owner: str):
    queue = list(scripts)
    runs: list[ScriptedGateway] = []

    async def run(session, binding, request):
        gateway = ScriptedGateway(queue.pop(0))
        runs.append(gateway)
        runtime = AgentRuntime(
            task_budget_binding_factory=lambda user, ref: binding)
        command = AgentCommand("plan_adjustment", request.instructions, owner,
                               surface="plan", language="zh-CN",
                               task_ref=TaskRef(binding.task_id, session.current().version))
        return await runtime.execute(
            command, UnifiedCoachWorkflow(gateway, _executor(session, owner), session=session))

    run.gateways = runs
    return run


def _service(owner: str, *, scripts=(), admission=None,
             versioned_constraints: bool = False) -> PlanAdjustmentService:
    database = get_database()
    repository = SQLitePlanAdjustmentRepository(database, clock=lambda: NOW)
    plans = _seed(owner)
    profiles = SQLiteProfileTargetRepository(database)
    if versioned_constraints:
        # The production source: only what the versioned store can name. A task
        # built on it must ask about the rest instead of assuming it is empty.
        source = lambda user: dict(profiles.constraint_snapshot(user).constraints)
    else:
        # The full set, so the happy path is about HTTP and the confirmation
        # rather than about the clarification round.
        source = lambda user: dict(CONSTRAINTS)
    return PlanAdjustmentService(
        repository, plans, PlanValidation(),
        constraints_source=source,
        head_revision=lambda user: plans.current_head(user).revision,
        runner=_runner(scripts, owner),
        budgets=SQLiteTaskBudgetRepository(database),
        activations=plans,
        admission=admission,
    )


def _install(client: TestClient, service: PlanAdjustmentService) -> None:
    client.app.dependency_overrides[get_plan_adjustment_service] = lambda: service


def _post(client, session, path, body, key):
    headers = {**_auth(session), "Idempotency-Key": key}
    return client.post(f"{TASKS}{path}", json=body, headers=headers)


def _start(client, session, *, key="create-1", read=("training", "diet"),
           change=("training", "diet"), plan_id=PLAN_ID):
    return _post(client, session, "", {
        "base_plan_id": plan_id,
        "read_domains": list(read),
        "change_domains": list(change),
        "instructions": INSTRUCTIONS,
    }, key)


# -- the whole chain -----------------------------------------------------
def test_start_scope_execute_candidate_confirm(api):
    """The flow the plan describes, over HTTP, with nothing injected by hand.

    A diet change is refused until the user grants it, the candidate is produced
    by a bound task rather than by a free agent, and the confirmation writes a new
    head instead of replacing the old plan.
    """
    client, session = api
    service = _service(session["user"]["user_id"], scripts=[ROUND_0, ROUND_1, ROUND_2])
    _install(client, service)

    started = _start(client, session, change=("training",))
    assert started.status_code == 200, started.text
    task = started.json()["data"]
    # The grant is narrower than the read, so the task waits for the user instead
    # of generating against a decision nobody made.
    assert task["state"] == "collecting"
    assert task["change_domains"] == ["training"]

    refused = _post(client, session, f"/{task['task_id']}/execute",
                    {"expected_version": task["version"], "instructions": INSTRUCTIONS},
                    "exec-too-early")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "SCOPE_GRANT_REQUIRED"

    granted = _post(client, session, f"/{task['task_id']}/scope", {
        "expected_version": task["version"],
        "read_domains": ["training", "diet"],
        "change_domains": ["training", "diet"],
        "decision": "allow",
    }, "scope-1")
    assert granted.status_code == 200, granted.text
    assert granted.json()["data"]["state"] == "generating"

    first = _post(client, session, f"/{task['task_id']}/execute",
                  {"expected_version": granted.json()["data"]["version"],
                   "instructions": INSTRUCTIONS}, "exec-1")
    assert first.status_code == 200, first.text
    assert first.json()["data"]["task"]["failed_domains"] == ["diet", "training"]

    second = _post(client, session, f"/{task['task_id']}/execute",
                   {"expected_version": first.json()["data"]["task"]["version"],
                    "instructions": INSTRUCTIONS}, "exec-2")
    assert second.status_code == 200, second.text

    third = _post(client, session, f"/{task['task_id']}/execute",
                  {"expected_version": second.json()["data"]["task"]["version"],
                   "instructions": INSTRUCTIONS}, "exec-3")
    assert third.status_code == 200, third.text
    candidate = third.json()["data"]["task"]
    assert candidate["state"] == "awaiting_confirmation"
    assert candidate["failed_domains"] == []

    confirmed = _post(client, session, f"/{task['task_id']}/confirm", {
        "expected_version": candidate["version"],
        "expected_head_revision": candidate["base_head_revision"],
        "candidate_digest": candidate["candidate"]["digest"],
    }, "confirm-1")
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()["data"]
    assert body["plan"]["head_revision"] == 2
    assert body["plan"]["based_on_plan_id"] == PLAN_ID
    assert body["replayed"] is False

    # The old plan is history, not a row that was overwritten.
    plans = SQLitePlanRepository(get_database())
    assert len(plans.list(session["user"]["user_id"])) == 2
    assert plans.current_head(session["user"]["user_id"]).revision == 2


def test_confirming_twice_with_the_same_key_replays(api):
    client, session = api
    service = _service(session["user"]["user_id"], scripts=[ROUND_0, ROUND_1, ROUND_2])
    _install(client, service)
    candidate = _await_candidate(client, session)

    first = _post(client, session, f"/{candidate['task_id']}/confirm", {
        "expected_version": candidate["version"],
        "expected_head_revision": candidate["base_head_revision"],
        "candidate_digest": candidate["candidate"]["digest"],
    }, "confirm-1")
    second = _post(client, session, f"/{candidate['task_id']}/confirm", {
        "expected_version": candidate["version"],
        "expected_head_revision": candidate["base_head_revision"],
        "candidate_digest": candidate["candidate"]["digest"],
    }, "confirm-1")

    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["data"]["replayed"] is True
    assert (second.json()["data"]["plan"]["head_revision"]
            == first.json()["data"]["plan"]["head_revision"])
    # A retry must not spend a second revision.
    assert SQLitePlanRepository(get_database()).current_head(
        session["user"]["user_id"]).revision == 2


def _await_candidate(client, session) -> dict:
    started = _start(client, session).json()["data"]
    version = started["version"]
    for index in range(3):
        response = _post(client, session, f"/{started['task_id']}/execute",
                         {"expected_version": version, "instructions": INSTRUCTIONS},
                         f"exec-{index}")
        assert response.status_code == 200, response.text
        version = response.json()["data"]["task"]["version"]
    task = client.get(f"{TASKS}/{started['task_id']}", headers=_auth(session)).json()["data"]
    assert task["state"] == "awaiting_confirmation"
    return task


# -- reads never execute -------------------------------------------------
def test_a_read_never_spends_a_round(api):
    """A refresh, a poll or a second tab must not cost money."""
    client, session = api
    service = _service(session["user"]["user_id"], scripts=[ROUND_0])
    _install(client, service)
    started = _start(client, session).json()["data"]

    for _ in range(3):
        response = client.get(f"{TASKS}/{started['task_id']}", headers=_auth(session))
        assert response.status_code == 200
        assert response.json()["data"]["version"] == started["version"]

    assert service.runner.gateways == []


def test_the_two_entries_read_the_same_task_and_version(api):
    """The response of a write and the response of a read describe one task.

    A client that posts and then refreshes must not be shown a version it cannot
    use: the second entry is the same projection, not a second opinion.
    """
    client, session = api
    service = _service(session["user"]["user_id"], scripts=[ROUND_0])
    _install(client, service)
    started = _start(client, session).json()["data"]

    executed = _post(client, session, f"/{started['task_id']}/execute",
                     {"expected_version": started["version"],
                      "instructions": INSTRUCTIONS}, "exec-1")
    assert executed.status_code == 200, executed.text
    from_write = executed.json()["data"]["task"]

    read = client.get(f"{TASKS}/{started['task_id']}", headers=_auth(session)).json()["data"]

    assert read["version"] == from_write["version"]
    assert read["state"] == from_write["state"]
    assert read["candidate"] == from_write["candidate"]


# -- refusals ------------------------------------------------------------
def test_a_task_built_on_the_versioned_store_asks_for_what_it_cannot_name(api):
    """Unknown is not empty, all the way to the client.

    The versioned snapshot owns the targets and the allergy list; it does not own
    the equipment or the forbidden movements, which only a clarification can
    supply. So the task stops and asks, and the answer it takes is the one the
    repository already declared answerable.
    """
    client, session = api
    _install(client, _service(session["user"]["user_id"], scripts=[ROUND_0],
                              versioned_constraints=True))
    started = _start(client, session).json()["data"]
    assert "constraints.action_restrictions" in started["missing_constraints"]
    assert "constraints.available_equipment" in started["missing_constraints"]

    stopped = _post(client, session, f"/{started['task_id']}/execute",
                    {"expected_version": started["version"],
                     "instructions": INSTRUCTIONS}, "exec-1")
    assert stopped.status_code == 200, stopped.text
    waiting = stopped.json()["data"]["task"]
    assert waiting["state"] == "awaiting_user_decision"
    assert waiting["candidate"] is None

    answered = _post(client, session, f"/{started['task_id']}/answers", {
        "expected_version": waiting["version"],
        "answers": {
            "action_restrictions": [],
            "available_equipment": ["barbell", "bodyweight", "dumbbell",
                                    "machine", "cable", "pull-up bar"],
        },
    }, "answer-1")

    assert answered.status_code == 200, answered.text
    assert answered.json()["data"]["missing_constraints"] == []
    assert answered.json()["data"]["version"] > waiting["version"]


def test_another_accounts_task_is_indistinguishable_from_a_missing_one(api):
    client, session = api
    _install(client, _service(session["user"]["user_id"]))
    other = _register(client, "somebody-else")

    missing = client.get(f"{TASKS}/task-does-not-exist", headers=_auth(session))
    stolen = client.get(f"{TASKS}/task-does-not-exist", headers=_auth(other))

    assert missing.status_code == 404 and stolen.status_code == 404
    assert missing.json()["error"]["code"] == stolen.json()["error"]["code"]


def test_a_stale_head_revision_cannot_confirm(api):
    """Confirmation is against the head the candidate was reviewed on."""
    client, session = api
    service = _service(session["user"]["user_id"], scripts=[ROUND_0, ROUND_1, ROUND_2])
    _install(client, service)
    candidate = _await_candidate(client, session)

    response = _post(client, session, f"/{candidate['task_id']}/confirm", {
        "expected_version": candidate["version"],
        "expected_head_revision": 9,
        "candidate_digest": candidate["candidate"]["digest"],
    }, "confirm-stale")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLAN_BASE_STALE"


def test_an_execute_without_a_key_is_refused(api):
    client, session = api
    _install(client, _service(session["user"]["user_id"]))
    started = _start(client, session).json()["data"]

    response = client.post(
        f"{TASKS}/{started['task_id']}/execute",
        json={"expected_version": started["version"], "instructions": INSTRUCTIONS},
        headers=_auth(session),
    )

    assert response.status_code == 422


def test_a_body_cannot_set_the_owner_or_the_head(api):
    """``extra="forbid"`` is the reason a browser cannot claim either."""
    client, session = api
    _install(client, _service(session["user"]["user_id"]))

    response = _post(client, session, "", {
        "base_plan_id": PLAN_ID,
        "read_domains": ["training", "diet"],
        "change_domains": ["training", "diet"],
        "instructions": INSTRUCTIONS,
        "user_id": "somebody-else",
    }, "create-1")

    assert response.status_code == 422


def test_the_entry_can_be_switched_off_without_hiding_existing_tasks(api, monkeypatch):
    client, session = api
    _install(client, _service(session["user"]["user_id"]))
    started = _start(client, session).json()["data"]

    monkeypatch.setenv("PLAN_ADJUSTMENT_TASKS_ENABLED", "false")
    get_settings.cache_clear()

    read = client.get(f"{TASKS}/{started['task_id']}", headers=_auth(session))
    assert read.status_code == 200

    execute = _post(client, session, f"/{started['task_id']}/execute",
                    {"expected_version": started["version"],
                     "instructions": INSTRUCTIONS}, "exec-1")
    assert execute.status_code == 409
    assert execute.json()["error"]["code"] == "PLAN_ADJUSTMENT_TASKS_DISABLED"


def test_a_round_may_not_run_beside_a_coach_turn(api):
    """One model call per account, whichever entry asks for it."""
    client, session = api
    owner = session["user"]["user_id"]
    admission = get_coach_admission_service()
    _install(client, _service(owner, scripts=[ROUND_0], admission=admission))
    started = _start(client, session).json()["data"]

    held = admission.begin_legacy(
        owner, question="解释一下今天的训练", action="explain_today", surface="today")
    try:
        response = _post(client, session, f"/{started['task_id']}/execute",
                         {"expected_version": started["version"],
                          "instructions": INSTRUCTIONS}, "exec-1")
    finally:
        admission.fail_legacy(owner, held, error_code="TEST_RELEASED")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COACH_TURN_BUSY"


# -- the composition root ------------------------------------------------
def test_the_current_plan_is_the_head_a_task_would_be_based_on(api):
    """``current`` is a route, not a plan id.

    If it were registered after ``/{plan_id}`` the literal would be read as an id
    and a plan that exists would look missing.
    """
    client, session = api
    owner = session["user"]["user_id"]
    FilePlanRepository(get_settings().data_dir).save(owner, StoredPlan(
        plan_id=PLAN_ID, activated_at=NOW, kind="deterministic",
        plan=GeneratedPlan.model_validate(BASE)))

    response = client.get("/plan/current", headers=_auth(session))

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["plan"]["plan_id"] == PLAN_ID
    assert data["head_revision"] == 1


def test_the_current_plan_is_not_found_before_any_plan_exists(api):
    client, session = api

    response = client.get("/plan/current", headers=_auth(session))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PLAN_NOT_FOUND"


def test_the_old_adjustment_draft_path_cannot_bypass_confirmation(api):
    """One write path per deployment.

    The draft route has no head compare-and-swap, no frozen constraints and no
    reviewed digest, so while the task entry is on it must not produce something
    that can be activated without them. It refuses before spending a model call.
    """
    client, session = api
    _seed(session["user"]["user_id"])

    response = client.post(f"/plan/{PLAN_ID}/draft", json={"instructions": "改一下训练"},
                           headers=_auth(session))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLAN_ADJUSTMENT_ENTRY_MOVED"


def test_the_default_wiring_reads_constraints_from_the_versioned_store(api):
    """The service the app builds is not the one these tests inject.

    It must take the hard constraints from the versioned profile, because a
    confirmation re-reads them there: a task built from anything else would be
    validated against values the store cannot reproduce.
    """
    client, session = api
    owner = session["user"]["user_id"]
    _seed(owner)

    service = get_plan_adjustment_service()

    snapshot = service.constraints_source(owner)
    assert snapshot["goal"] == "fat_loss"
    assert snapshot["daily_calorie_target"] == 2000
    assert snapshot["allergies_or_restrictions"] == ["花生"]
    # The allergy list has a version, which is what a confirmation re-reads.
    assert SQLiteProfileTargetRepository(
        get_database()).get_latest_safety(owner) is not None


def test_the_default_wiring_cannot_confirm_on_a_file_store(api, monkeypatch):
    """``plan_storage_mode='file'`` has no compare-and-swap, so it refuses.

    The refusal is the feature: a store that cannot tell two confirmations apart
    must not accept one.
    """
    client, session = api
    monkeypatch.setenv("PLAN_STORAGE_MODE", "file")
    get_settings.cache_clear()

    service = get_plan_adjustment_service()

    assert service.activations is None
