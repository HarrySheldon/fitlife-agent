"""HTTP surface of plan adjustment tasks.

This module translates HTTP into one service call and back. It owns no rule: the
grant, the frozen constraints, the rounds, the candidate and the atomic
confirmation all live in ``PlanAdjustmentService`` and the stores behind it, so a
second entry -- the coach, a future worker -- cannot get a different answer by
going around them.

Four properties matter at this layer.

*Reading never executes.* Every ``GET`` is a repository read. There is no path
from a read to a provider call, so a poll, a refresh or a second tab cannot spend
money.

*Identity comes from the token.* The owner is never a body field. Unknown tasks
and other people's tasks answer the same 404, so a wrong id cannot be used to
ask whether a task exists.

*Retries are explicit.* Every ``POST`` requires ``Idempotency-Key``; every
mutation requires ``expected_version``. A confirmation additionally requires the
head revision it was reviewed against and the candidate digest, because "confirm
whatever is newest" is not a decision the user made.

*The entry is switchable.* ``plan_adjustment_tasks_enabled`` gates the mutations
only: turning the entry off must not hide a task that already exists, so reads
keep working and nothing already produced becomes unreachable.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from backend.agent.contracts import AgentCommand
from backend.agent.context_builder import ExecutionPrincipal
from backend.agent.plan_adjustment.validation import PlanValidation
from backend.agent.skills.catalog import SkillCatalog
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.handlers import BoundFitnessReads
from backend.agent.tasks.contracts import TaskRef
from backend.agent.plan_adjustment.tools import PLAN_TOOL_SPECS
from backend.agent.runtime import AgentRuntime
from backend.agent.unified_coach import UnifiedCoachWorkflow
from backend.api.coach_conversations import coach_error, get_coach_admission_service
from backend.api.dependencies import require_current_user
from backend.api.utils import ok
from backend.application.use_cases.plan_adjustment import (
    MAX_INSTRUCTIONS,
    PlanAdjustmentService,
    RoundRequest,
)
from backend.application.ports.plan_repository import legacy_head
from backend.config import get_settings
from backend.domain.errors import ApplicationError, configuration_error
from backend.infrastructure.auth.file_identity_repository import FileIdentityRepository
from backend.infrastructure.model_gateway.agent_decision_adapter import (
    StructuredDecisionAdapter,
)
from backend.infrastructure.model_gateway.factory import resolve_user_model_gateway
from backend.infrastructure.repositories.cutover_fitness_repository import (
    get_fitness_repository,
)
from backend.infrastructure.repositories.plan_repository_factory import (
    build_plan_activation_repository,
    build_plan_repository,
)
from backend.infrastructure.repositories.sqlite_plan_adjustment_repository import (
    SQLitePlanAdjustmentRepository,
)
from backend.infrastructure.repositories.sqlite_profile_target_repository import (
    SQLiteProfileTargetRepository,
)
from backend.infrastructure.repositories.sqlite_task_budget_repository import (
    SQLiteTaskBudgetRepository,
)
from backend.infrastructure.sqlite.runtime import get_database
from backend.schemas import AuthenticatedUser


router = APIRouter(prefix="/api/v1/plan-adjustment-tasks")

Domain = Literal["training", "diet"]


# -- request bodies ------------------------------------------------------
class TaskStartRequest(BaseModel):
    """What a client may say about a new task.

    Owner, head revision, task id and state are absent on purpose: ``extra``
    rejects them, so a browser cannot claim a head it was not shown or start a
    task already at a state of its choosing.
    """

    model_config = ConfigDict(extra="forbid")

    base_plan_id: str = Field(pattern=r"^plan-[a-f0-9]{8,64}$")
    read_domains: list[Domain] = Field(min_length=1, max_length=2)
    change_domains: list[Domain] = Field(min_length=1, max_length=2)
    instructions: str = Field(min_length=1, max_length=MAX_INSTRUCTIONS)


class ScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    read_domains: list[Domain] = Field(min_length=1, max_length=2)
    change_domains: list[Domain] = Field(min_length=1, max_length=2)
    decision: Literal["allow", "deny"]


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    answers: dict[str, object] = Field(min_length=1, max_length=8)


class ExecuteRequest(BaseModel):
    """A round needs the request it serves.

    The prose is not stored on the task -- the conversation owns the words -- so
    every round restates it, including a repair after a failed candidate.
    """

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    instructions: str = Field(min_length=1, max_length=MAX_INSTRUCTIONS)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    expected_head_revision: int = Field(ge=1)
    candidate_digest: str = Field(min_length=8, max_length=128)


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


# -- service wiring ------------------------------------------------------
_SERVICES: dict[str, PlanAdjustmentService] = {}


def _disabled() -> ApplicationError:
    return ApplicationError(
        code="PLAN_ADJUSTMENT_TASKS_DISABLED",
        message="Plan adjustment tasks are not enabled in this deployment.",
        status_code=409,
        processing_mode="agent",
    )


def require_enabled() -> None:
    """Gate the mutations only.

    Turning the entry off stops new model work; it does not erase a candidate the
    user was already shown, so reads stay open.
    """
    if not get_settings().plan_adjustment_tasks_enabled:
        raise _disabled()


def _build(settings) -> PlanAdjustmentService:
    database = get_database()
    repository = SQLitePlanAdjustmentRepository(database)
    budgets = SQLiteTaskBudgetRepository(database)
    profiles = SQLiteProfileTargetRepository(database)
    plans = build_plan_repository(settings)
    try:
        activations = build_plan_activation_repository(settings)
    except ApplicationError:
        # A file store cannot compare-and-swap a head. Leaving ``activations``
        # empty is how the service knows to refuse a confirmation instead of
        # writing a plan through a door that cannot tell two writers apart.
        activations = None

    def head_revision(owner: str) -> int:
        head = plans.current_head(owner)
        if head is None and getattr(settings, "plan_storage_mode", "file") == "file":
            # The file store has no head row, so the legacy rule supplies one. It
            # is *not* used as a fallback in sqlite mode: a database without a head
            # means the head is absent, and inventing one would pin a task to a
            # plan the authoritative store does not consider current.
            head = legacy_head(plans.list(owner))
        return head.revision if head is not None else 0

    def constraints_source(owner: str) -> dict:
        return dict(profiles.constraint_snapshot(owner).constraints)

    return PlanAdjustmentService(
        repository, plans, PlanValidation(),
        constraints_source=constraints_source,
        head_revision=head_revision,
        runner=_runner(settings),
        budgets=budgets,
        activations=activations,
        admission=_admission(),
        # No plan-candidate reviewer is wired in this checkpoint, so demanding a
        # review would refuse every confirmation rather than make one safer. The
        # flag stays a policy statement: when a reviewer exists, set it from the
        # policy that requires it, not from this default.
        review_required=False,
    )


def _admission():
    """The account's single model slot, shared with every coach entry."""
    return get_coach_admission_service()


def _runner(settings):
    """The composition root of a plan round: runtime, gateway, closed tool set.

    Two things are deliberately not configurable here.

    The tools are ``PLAN_TOOL_SPECS`` and nothing else, so a model inside a plan
    task cannot read a meal log or call a calculator the task never granted.

    The domains come from the task row, not from the request text, so a task that
    was granted training only cannot widen itself by describing a diet.
    """
    identities = FileIdentityRepository(settings.data_dir)

    async def run(session, binding, request: RoundRequest):
        owner = session.owner
        snapshot = session.current()
        gateway = resolve_user_model_gateway(owner)
        if not callable(getattr(gateway, "parse_structured", None)):
            # The task loop needs one bounded decision maker. Falling back to a
            # different chain here would mean the same request is judged by a
            # different engine depending on the deployment's gateway.
            raise configuration_error(
                "Plan tasks require the unified structured decision engine.")
        token_version = identities.get_token_version(owner)
        if token_version is None:
            raise PermissionError("AUTHENTICATED_OWNER_REQUIRED")
        principal = ExecutionPrincipal(
            owner, authorized_domains=frozenset(snapshot.read_domains))

        def authorize(actor):
            if (actor.owner_id != owner
                    or identities.get_token_version(owner) != token_version):
                raise PermissionError("ACCOUNT_ACCESS_REVOKED")
            if not get_settings().plan_adjustment_tasks_enabled:
                raise PermissionError("PLAN_ADJUSTMENT_TASKS_DISABLED")
            return principal.authorized_domains

        executor = ToolExecutor(
            principal=principal,
            # The plan tools never read the fitness store; it is supplied because
            # the executor's context is one shape for every task kind, and a
            # half-built context is how a later tool gets added without noticing
            # which reads it can reach.
            reads=BoundFitnessReads(get_fitness_repository(), owner),
            catalog=SkillCatalog(),
            authorize=authorize,
            retriever=lambda query, top_k: [],
            specs=PLAN_TOOL_SPECS,
            session=session,
        )
        workflow = UnifiedCoachWorkflow(
            StructuredDecisionAdapter(gateway), executor, session=session)
        command = AgentCommand(
            "plan_adjustment", request.instructions, owner, surface="plan",
            task_ref=TaskRef(snapshot.task_id, snapshot.version),
        )
        runtime = AgentRuntime(
            task_budget_binding_factory=lambda user, ref: binding)
        return await runtime.execute(command, workflow)

    return run


def get_plan_adjustment_service() -> PlanAdjustmentService:
    settings = get_settings()
    key = str(settings.database_path)
    service = _SERVICES.get(key)
    if service is None:
        service = _build(settings)
        _SERVICES[key] = service
    return service


def reset_plan_adjustment_services() -> None:
    """Drop cached services. Used by tests and by a data-directory switch."""
    _SERVICES.clear()


# -- routes --------------------------------------------------------------
@router.post("")
def start_task(
    body: TaskStartRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
    user: AuthenticatedUser = Depends(require_current_user),
    service: PlanAdjustmentService = Depends(get_plan_adjustment_service),
    _: None = Depends(require_enabled),
):
    task = service.start(
        user.user_id, body.base_plan_id,
        frozenset(body.read_domains), frozenset(body.change_domains),
        body.instructions, key=idempotency_key,
    )
    return ok(task, processing_mode="agent")


@router.get("/{task_id}")
def get_task(
    task_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    service: PlanAdjustmentService = Depends(get_plan_adjustment_service),
):
    # Reads are open even when the entry is switched off: a task the user already
    # started must not disappear because a deployment flag changed.
    return ok(service.get(user.user_id, task_id), processing_mode="agent")


@router.post("/{task_id}/scope")
def decide_scope(
    task_id: str,
    body: ScopeRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
    user: AuthenticatedUser = Depends(require_current_user),
    service: PlanAdjustmentService = Depends(get_plan_adjustment_service),
    _: None = Depends(require_enabled),
):
    task = service.grant(
        user.user_id, task_id, body.expected_version,
        frozenset(body.read_domains), frozenset(body.change_domains),
        body.decision, key=idempotency_key,
    )
    return ok(task, processing_mode="agent")


@router.post("/{task_id}/answers")
def answer_task(
    task_id: str,
    body: AnswerRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
    user: AuthenticatedUser = Depends(require_current_user),
    service: PlanAdjustmentService = Depends(get_plan_adjustment_service),
    _: None = Depends(require_enabled),
):
    task = service.answer(
        user.user_id, task_id, body.expected_version, body.answers,
        key=idempotency_key,
    )
    return ok(task, processing_mode="agent")


@router.post("/{task_id}/execute")
async def execute_task(
    task_id: str,
    body: ExecuteRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
    user: AuthenticatedUser = Depends(require_current_user),
    service: PlanAdjustmentService = Depends(get_plan_adjustment_service),
    _: None = Depends(require_enabled),
):
    try:
        result = await service.execute(
            user.user_id, task_id, body.expected_version, idempotency_key,
            instructions=body.instructions,
        )
    except Exception as error:
        # A busy slot is a refusal the user can act on, not a server fault. The
        # translation is shared with the coach so both entries report it the same
        # way; anything unrecognised is re-raised rather than dressed up.
        raise coach_error(error) from None
    return ok(result, processing_mode="agent")


@router.post("/{task_id}/confirm")
def confirm_task(
    task_id: str,
    body: ConfirmRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
    user: AuthenticatedUser = Depends(require_current_user),
    service: PlanAdjustmentService = Depends(get_plan_adjustment_service),
    _: None = Depends(require_enabled),
):
    result = service.confirm(
        user.user_id, task_id, body.expected_version,
        body.expected_head_revision, body.candidate_digest, key=idempotency_key,
    )
    return ok(result, processing_mode="agent")


@router.post("/{task_id}/cancel")
def cancel_task(
    task_id: str,
    body: CancelRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
    user: AuthenticatedUser = Depends(require_current_user),
    service: PlanAdjustmentService = Depends(get_plan_adjustment_service),
    _: None = Depends(require_enabled),
):
    task = service.cancel(
        user.user_id, task_id, body.expected_version, key=idempotency_key)
    return ok(task, processing_mode="agent")
