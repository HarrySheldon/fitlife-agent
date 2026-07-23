from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from string import hexdigits
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from backend.api.dependencies import require_current_user
from backend.api.utils import ok
from backend.application.ports.profile_target_repository import (
    GoalVersionInput,
    ProfileVersionInput,
)
from backend.application.use_cases.profile_targets import (
    FileLegacyProfileProjection,
    ProfileTargetService,
    TargetPreview,
    TargetServiceError,
)
from backend.domain.profile_targets import DailyTargets
from backend.infrastructure.repositories.file_fitness_repository import (
    FileFitnessRepository,
)
from backend.infrastructure.repositories.sqlite_profile_target_repository import (
    SQLiteProfileTargetRepository,
)
from backend.infrastructure.sqlite.runtime import get_database
from backend.schemas import (
    AuthenticatedUser,
    OverallGoalUpdateRequest,
    ProfileVersionUpdateRequest,
    TargetCalculateRequest,
    TargetConfirmRequest,
)


router = APIRouter(prefix="/api/v1")


def get_profile_target_service() -> ProfileTargetService:
    return ProfileTargetService(
        SQLiteProfileTargetRepository(get_database()),
        FileLegacyProfileProjection(FileFitnessRepository()),
    )


@router.get("/profile")
def get_profile_setup(
    user: AuthenticatedUser = Depends(require_current_user),
    service: ProfileTargetService = Depends(get_profile_target_service),
):
    result = service.get_setup(user.user_id)
    return ok(
        {
            "profile": _dataclass_or_none(result.profile),
            "goal": _dataclass_or_none(result.goal),
            "target": _dataclass_or_none(result.target),
            "setup_complete": result.setup_complete,
        },
        processing_mode="deterministic",
    )


@router.put("/profile")
def update_profile(
    payload: ProfileVersionUpdateRequest,
    user: AuthenticatedUser = Depends(require_current_user),
    service: ProfileTargetService = Depends(get_profile_target_service),
):
    result = service.update_profile(
        user.user_id,
        ProfileVersionInput(
            age=payload.age,
            height_cm=payload.height_cm,
            weight_kg=payload.weight_kg,
            energy_parameter=payload.energy_parameter,
            activity_level=payload.activity_level,
            auto_target_disabled=payload.auto_target_disabled,
            safety_conditions=tuple(payload.safety_conditions),
            effective_from=_canonical_utc(payload.effective_from),
        ),
    )
    return ok(_mutation_data(result), processing_mode="deterministic")


@router.get("/goals")
def get_goals(
    user: AuthenticatedUser = Depends(require_current_user),
    service: ProfileTargetService = Depends(get_profile_target_service),
):
    goal = service.get_setup(user.user_id).goal
    return ok(
        {"overall": _dataclass_or_none(goal)},
        processing_mode="deterministic",
    )


@router.put("/goals/overall")
def update_overall_goal(
    payload: OverallGoalUpdateRequest,
    user: AuthenticatedUser = Depends(require_current_user),
    service: ProfileTargetService = Depends(get_profile_target_service),
):
    result = service.update_goal(
        user.user_id,
        GoalVersionInput(
            goal=payload.goal,
            effective_from=_canonical_utc(payload.effective_from),
        ),
    )
    return ok(_mutation_data(result), processing_mode="deterministic")


@router.post("/targets/calculate")
def calculate_targets(
    payload: TargetCalculateRequest,
    user: AuthenticatedUser = Depends(require_current_user),
    service: ProfileTargetService = Depends(get_profile_target_service),
):
    manual_targets = (
        _daily_targets(payload.manual_targets)
        if payload.manual_targets is not None
        else None
    )
    preview = service.calculate_preview(
        user.user_id,
        manual_targets=manual_targets,
    )
    return ok(_preview_data(preview), processing_mode="deterministic")


@router.post("/targets/confirm")
def confirm_targets(
    payload: TargetConfirmRequest,
    user: AuthenticatedUser = Depends(require_current_user),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    service: ProfileTargetService = Depends(get_profile_target_service),
):
    preview_token = _require_preview_token(if_match)
    normalized_idempotency_key = _require_idempotency_key(idempotency_key)
    body_preview_token = _require_preview_token(payload.preview.preview_token)
    if body_preview_token != preview_token:
        raise TargetServiceError("TARGET_PREVIEW_INVALID", status_code=422)
    preview = TargetPreview(
        profile_version_id=payload.preview.profile_version_id,
        overall_goal_version_id=payload.preview.overall_goal_version_id,
        targets=DailyTargets(
            calories=payload.preview.targets.calories,
            carbs=payload.preview.targets.carbs,
            protein=payload.preview.targets.protein,
            fat=payload.preview.targets.fat,
            formula_version=payload.preview.formula_version,
        ),
        source=payload.preview.source,
        warnings=tuple(payload.preview.warnings),
        requires_confirmation=payload.preview.requires_confirmation,
        preview_token=preview_token,
    )

    result = service.confirm_target(
        user.user_id,
        preview=preview,
        idempotency_key=normalized_idempotency_key,
        effective_from=_canonical_utc(payload.effective_from),
        acknowledge_warnings=payload.acknowledge_warnings,
    )
    return ok(
        {"target": asdict(result.target)},
        processing_mode="deterministic",
    )


@router.get("/targets/history")
def target_history(
    user: AuthenticatedUser = Depends(require_current_user),
    service: ProfileTargetService = Depends(get_profile_target_service),
):
    targets = service.list_target_history(user.user_id)
    return ok(
        [asdict(target) for target in targets],
        processing_mode="deterministic",
    )


def _canonical_utc(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _daily_targets(payload) -> DailyTargets:
    return DailyTargets(
        calories=payload.calories,
        carbs=payload.carbs,
        protein=payload.protein,
        fat=payload.fat,
    )


def _mutation_data(result) -> dict:
    return {
        "profile": _dataclass_or_none(result.profile),
        "goal": _dataclass_or_none(result.goal),
        "recalculation_preview": (
            _preview_data(result.recalculation_preview)
            if result.recalculation_preview is not None
            else None
        ),
        "recalculation_restriction": result.recalculation_restriction,
    }


def _preview_data(preview: TargetPreview) -> dict:
    return {
        "profile_version_id": preview.profile_version_id,
        "overall_goal_version_id": preview.overall_goal_version_id,
        "targets": {
            "calories": preview.targets.calories,
            "carbs": preview.targets.carbs,
            "protein": preview.targets.protein,
            "fat": preview.targets.fat,
        },
        "source": preview.source,
        "formula_version": preview.targets.formula_version,
        "warnings": list(preview.warnings),
        "requires_confirmation": preview.requires_confirmation,
        "preview_token": preview.preview_token,
    }


def _dataclass_or_none(value):
    return asdict(value) if value is not None else None


def _require_preview_token(value: str | None) -> str:
    if value is None:
        raise TargetServiceError("TARGET_PREVIEW_TOKEN_REQUIRED", status_code=422)
    token = value.strip()
    if len(token) == 66 and token.startswith('"') and token.endswith('"'):
        token = token[1:-1]
    if len(token) != 64 or any(character not in hexdigits for character in token):
        raise TargetServiceError("TARGET_PREVIEW_INVALID", status_code=422)
    return token.lower()


def _require_idempotency_key(value: str | None) -> str:
    if value is None:
        raise TargetServiceError("IDEMPOTENCY_KEY_REQUIRED", status_code=422)
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise TargetServiceError("INVALID_IDEMPOTENCY_KEY", status_code=422) from None
