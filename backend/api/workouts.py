from __future__ import annotations

from dataclasses import asdict
import re
from uuid import UUID

from datetime import date

from fastapi import APIRouter, Depends, Header, Query

from backend.api.dependencies import require_current_user
from backend.api.preference_context import preferences_for
from backend.api.utils import ok
from backend.api.workout_schemas import (
    CardioItemRequest,
    ConfirmedWorkoutResponse,
    CustomExerciseValuesRequest,
    DeletedResponse,
    StrengthExerciseRequest,
    WorkoutDraftResponse,
    WorkoutDraftMutationRequest,
)
from backend.application.ports.workout_repository import (
    CardioItemInput,
    CustomExerciseSnapshot,
    StrengthExerciseInput,
    WorkoutDraftInput,
)
from backend.application.use_cases.workouts import (
    WorkoutService,
    WorkoutServiceError,
)
from backend.config import get_settings
from backend.domain.workouts import StrengthSet
from backend.infrastructure.repositories.sqlite_workout_repository import (
    SQLiteWorkoutRepository,
)
from backend.infrastructure.sqlite.runtime import get_database
from backend.infrastructure.user_lifecycle import user_lifecycle_guard
from backend.schemas import ApiResponse, AuthenticatedUser


router = APIRouter(prefix="/api/v1/workout-drafts")


def get_workout_service() -> WorkoutService:
    return WorkoutService(
        SQLiteWorkoutRepository(get_database()),
        mutation_scope=lambda user_id: user_lifecycle_guard(
            get_settings().data_dir,
            user_id,
        ),
    )


@router.post("", response_model=ApiResponse[WorkoutDraftResponse])
def create_draft(
    payload: WorkoutDraftMutationRequest,
    user: AuthenticatedUser = Depends(require_current_user),
    service: WorkoutService = Depends(get_workout_service),
):
    return ok(
        asdict(service.create_draft(user.user_id, _input(payload))),
        processing_mode="deterministic",
    )


@router.get("", response_model=ApiResponse[WorkoutDraftResponse | None])
def find_latest_draft(
    log_date: date = Query(alias="date"),
    user: AuthenticatedUser = Depends(require_current_user),
    service: WorkoutService = Depends(get_workout_service),
):
    draft = service.find_latest_draft(user.user_id, log_date.isoformat())
    return ok(
        asdict(draft) if draft is not None else None,
        processing_mode="deterministic",
    )


@router.get("/{draft_id}", response_model=ApiResponse[WorkoutDraftResponse])
def get_draft(
    draft_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    service: WorkoutService = Depends(get_workout_service),
):
    draft = service.get_draft(user.user_id, draft_id)
    if draft is None:
        raise WorkoutServiceError("WORKOUT_DRAFT_NOT_FOUND", status_code=404)
    return ok(asdict(draft), processing_mode="deterministic")


@router.patch("/{draft_id}", response_model=ApiResponse[WorkoutDraftResponse])
def update_draft(
    draft_id: str,
    payload: WorkoutDraftMutationRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: AuthenticatedUser = Depends(require_current_user),
    service: WorkoutService = Depends(get_workout_service),
):
    updated = service.update_draft(
        user.user_id,
        draft_id,
        expected_version=_version(if_match),
        payload=_input(payload),
    )
    return ok(asdict(updated), processing_mode="deterministic")


@router.delete("/{draft_id}", response_model=ApiResponse[DeletedResponse])
def delete_draft(
    draft_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    service: WorkoutService = Depends(get_workout_service),
):
    service.delete_draft(user.user_id, draft_id)
    return ok({"deleted": True}, processing_mode="deterministic")


@router.post(
    "/{draft_id}/confirm",
    response_model=ApiResponse[ConfirmedWorkoutResponse],
)
def confirm_draft(
    draft_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    user: AuthenticatedUser = Depends(require_current_user),
    service: WorkoutService = Depends(get_workout_service),
):
    confirmed = service.confirm_draft(
        user.user_id,
        draft_id,
        expected_version=_version(if_match),
        idempotency_key=_idempotency_key(idempotency_key),
        timezone_name=preferences_for(user).timezone,
    )
    return ok(asdict(confirmed), processing_mode="deterministic")


def _input(payload: WorkoutDraftMutationRequest) -> WorkoutDraftInput:
    return WorkoutDraftInput(
        log_date=payload.log_date.isoformat(),
        title=payload.title,
        started_at=(
            payload.started_at.isoformat() if payload.started_at else None
        ),
        duration_min=payload.duration_min,
        intensity=payload.intensity,
        entry_method="form",
        strength_exercises=tuple(
            _strength(item) for item in payload.strength_exercises
        ),
        cardio_items=tuple(_cardio(item) for item in payload.cardio_items),
        recovery_state=payload.recovery_state,
    )


def _strength(item: StrengthExerciseRequest) -> StrengthExerciseInput:
    return StrengthExerciseInput(
        catalog_exercise_id=item.catalog_exercise_id,
        custom_exercise=(
            _custom(item.custom_exercise)
            if item.custom_exercise is not None
            else None
        ),
        sets=tuple(
            StrengthSet(
                set_number=value.set_number,
                reps=value.reps,
                load_kg=value.load_kg,
                bodyweight=value.bodyweight,
            )
            for value in item.sets
        ),
    )


def _cardio(item: CardioItemRequest) -> CardioItemInput:
    return CardioItemInput(
        catalog_exercise_id=item.catalog_exercise_id,
        custom_exercise=(
            _custom(item.custom_exercise)
            if item.custom_exercise is not None
            else None
        ),
        duration_min=item.duration_min,
        device_calories=item.device_calories,
    )


def _custom(
    item: CustomExerciseValuesRequest,
) -> CustomExerciseSnapshot:
    return CustomExerciseSnapshot(
        name=item.name,
        exercise_type=item.exercise_type,
        primary_muscle=item.primary_muscle,
        secondary_muscles=tuple(item.secondary_muscles),
        met=item.met,
    )


def _version(value: str | None) -> int:
    if value is None:
        raise WorkoutServiceError(
            "WORKOUT_DRAFT_VERSION_REQUIRED",
            status_code=422,
        )
    token = value.strip()
    if re.fullmatch(r'(?:[1-9]\d{0,18}|"[1-9]\d{0,18}")', token) is None:
        raise WorkoutServiceError(
            "WORKOUT_DRAFT_VERSION_INVALID",
            status_code=422,
        )
    version = int(token.strip('"'))
    if version > 9_223_372_036_854_775_807:
        raise WorkoutServiceError(
            "WORKOUT_DRAFT_VERSION_INVALID",
            status_code=422,
        )
    return version


def _idempotency_key(value: str | None) -> str:
    if value is None:
        raise WorkoutServiceError(
            "IDEMPOTENCY_KEY_REQUIRED",
            status_code=422,
        )
    try:
        return str(UUID(value))
    except (AttributeError, ValueError):
        raise WorkoutServiceError(
            "INVALID_IDEMPOTENCY_KEY",
            status_code=422,
        ) from None
