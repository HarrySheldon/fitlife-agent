from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request

from backend.agent.graph import interpret_persisted_plan
from backend.agent.validator import validate_generated_plan
from backend.api.dependencies import optional_current_user, require_current_user
from backend.api.preference_context import preferences_for
from backend.api.utils import ok, request_id_for
from backend.application.ports.model_gateway import ConfigurableModelGateway
from backend.application.ports.plan_repository import StoredPlan
from backend.application.use_cases.generate_plan import GeneratePlan
from backend.application.use_cases.plans import Plans
from backend.config import get_settings
from backend.domain.errors import ApplicationError, model_gateway_error
from backend.infrastructure.model_gateway.factory import resolve_user_model_gateway
from backend.infrastructure.repositories.cutover_fitness_repository import get_fitness_repository
from backend.infrastructure.repositories.file_plan_repository import FilePlanRepository
from backend.infrastructure.user_lifecycle import user_lifecycle_guard
from backend.schemas import AuthenticatedUser, CoachActionResponse, GeneratedPlan, PlanActivationRequest, PlanAdjustmentDraftRequest


router = APIRouter(prefix="/plan")

_ADJUSTMENT_INSTRUCTIONS = """Adjust the supplied active fitness plan according to the user's instructions.
Return the complete adjusted diet_plan and workout_plan, retain safe useful details from the active plan,
and include a validation object and trace object. Never activate or persist a plan."""


def generate_adjusted_plan(
    user_id: str,
    active: StoredPlan,
    instructions: str,
    *,
    gateway: ConfigurableModelGateway | None = None,
) -> dict:
    gateway = gateway or resolve_user_model_gateway(user_id)
    context = {
        "active_plan_id": active.plan_id,
        "active_plan": active.plan.model_dump(mode="json"),
        "adjustment_instructions": instructions,
    }
    try:
        result = gateway.parse_structured(
            instructions=_ADJUSTMENT_INSTRUCTIONS,
            input_text=json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            response_model=GeneratedPlan,
        )
    except ApplicationError:
        raise
    except Exception as error:
        raise model_gateway_error(error) from None
    generated = result.output.model_dump()
    generated["trace"] = {
        **generated.get("trace", {}),
        "agent_model": result.model,
        "agent_usage": result.usage,
        "based_on_plan_id": active.plan_id,
    }
    return generated


def _plans() -> Plans:
    fitness = get_fitness_repository()

    def deterministic(user_id: str) -> dict:
        return GeneratePlan(fitness).execute(user_id)

    def adjusted(user_id: str, active: StoredPlan, instructions: str) -> dict:
        with user_lifecycle_guard(get_settings().data_dir, user_id):
            return generate_adjusted_plan(user_id, active, instructions)

    return Plans(
        FilePlanRepository(get_settings().data_dir),
        deterministic,
        adjusted,
        lambda user_id, plan: validate_generated_plan(
            plan,
            fitness.read_profile(user_id).model_dump(),
        ),
    )


@router.get("")
def list_plans(user: AuthenticatedUser = Depends(require_current_user)):
    plans = [item.model_dump(mode="json") for item in _plans().list(user.user_id)]
    return ok(plans, processing_mode="deterministic")


@router.post("/draft")
def create_plan_draft(user: AuthenticatedUser = Depends(require_current_user)):
    draft = _plans().draft(user.user_id)
    return ok(draft.model_dump(mode="json"), processing_mode="deterministic")


@router.post("/activate")
def activate_plan(request: PlanActivationRequest, user: AuthenticatedUser = Depends(require_current_user)):
    stored = _plans().activate(user.user_id, request.draft_id)
    return ok(stored.model_dump(mode="json"), processing_mode="deterministic")


@router.post("/generate")
def generate_plan(user: AuthenticatedUser | None = Depends(optional_current_user)):
    """Compatibility endpoint: generate a validated plan without activating it."""
    plan = GeneratePlan(get_fitness_repository()).execute(user.user_id if user else None)
    return ok(plan, processing_mode="deterministic")


@router.post("/{plan_id}/draft")
def create_adjustment_draft(
    plan_id: str,
    request: PlanAdjustmentDraftRequest,
    user: AuthenticatedUser = Depends(require_current_user),
):
    draft = _plans().adjustment_draft(user.user_id, plan_id, request.instructions)
    return ok(draft.model_dump(mode="json"), processing_mode="agent")


@router.post("/{plan_id}/interpret")
def interpret_plan(plan_id: str, request: Request, user: AuthenticatedUser = Depends(require_current_user)):
    with user_lifecycle_guard(get_settings().data_dir, user.user_id):
        stored = _plans().get(user.user_id, plan_id)
        result = interpret_persisted_plan(
            plan_id=stored.plan_id,
            plan=stored.plan.model_dump(mode="json"),
            user_id=user.user_id,
            preferences=preferences_for(user),
            request_id=request_id_for(request),
        )
        response = CoachActionResponse(
            surface="plan",
            action="adjust_next_plan",
            answer_markdown=result["answer_markdown"],
            intent=result["intent"],
            trace=result["trace"],
            sources=result.get("sources", []),
            model=result["model"],
            request_id=result["request_id"],
            run_id=result.get("run_id", ""),
        )
        return ok(response.model_dump(), processing_mode="agent")


@router.get("/{plan_id}")
def get_plan(plan_id: str, user: AuthenticatedUser = Depends(require_current_user)):
    stored = _plans().get(user.user_id, plan_id)
    return ok(stored.model_dump(mode="json"), processing_mode="deterministic")
