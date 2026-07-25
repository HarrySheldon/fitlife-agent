from dataclasses import asdict

from fastapi import APIRouter, Depends, Query

from backend.api.dependencies import require_current_user
from backend.api.utils import ok
from backend.api.workout_schemas import (
    CustomExerciseRequest,
    ExerciseCatalogItemResponse,
    FavoriteResponse,
)
from backend.application.use_cases.exercise_catalog import (
    CustomExerciseCommand,
    ExerciseCatalogService,
)
from backend.config import get_settings
from backend.infrastructure.repositories.sqlite_exercise_catalog_repository import (
    SQLiteExerciseCatalogRepository,
)
from backend.infrastructure.sqlite.runtime import get_database
from backend.infrastructure.user_lifecycle import user_lifecycle_guard
from backend.schemas import ApiResponse, AuthenticatedUser


router = APIRouter(prefix="/api/v1/catalog/exercises")


def get_exercise_catalog_service() -> ExerciseCatalogService:
    return ExerciseCatalogService(
        SQLiteExerciseCatalogRepository(get_database()),
        mutation_scope=lambda user_id: user_lifecycle_guard(
            get_settings().data_dir,
            user_id,
        ),
    )


@router.get(
    "/search",
    response_model=ApiResponse[list[ExerciseCatalogItemResponse]],
)
def search_exercises(
    q: str = Query(default="", max_length=256),
    limit: int = Query(default=20, ge=1, le=50),
    user: AuthenticatedUser = Depends(require_current_user),
    service: ExerciseCatalogService = Depends(get_exercise_catalog_service),
):
    return ok(
        [
            asdict(item)
            for item in service.search(user.user_id, q, limit=limit)
        ],
        processing_mode="deterministic",
    )


@router.post(
    "/custom",
    response_model=ApiResponse[ExerciseCatalogItemResponse],
)
def create_custom_exercise(
    payload: CustomExerciseRequest,
    user: AuthenticatedUser = Depends(require_current_user),
    service: ExerciseCatalogService = Depends(get_exercise_catalog_service),
):
    created = service.create_custom_exercise(
        user.user_id,
        CustomExerciseCommand(
            name=payload.name,
            exercise_type=payload.exercise_type,
            primary_muscle=payload.primary_muscle,
            secondary_muscles=tuple(payload.secondary_muscles),
            met=payload.met,
            aliases=tuple(payload.aliases),
        ),
    )
    return ok(asdict(created), processing_mode="deterministic")


@router.put(
    "/{exercise_id}/favorite",
    response_model=ApiResponse[FavoriteResponse],
)
def add_favorite(
    exercise_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    service: ExerciseCatalogService = Depends(get_exercise_catalog_service),
):
    service.set_favorite(user.user_id, exercise_id, True)
    return ok({"favorite": True}, processing_mode="deterministic")


@router.delete(
    "/{exercise_id}/favorite",
    response_model=ApiResponse[FavoriteResponse],
)
def remove_favorite(
    exercise_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    service: ExerciseCatalogService = Depends(get_exercise_catalog_service),
):
    service.set_favorite(user.user_id, exercise_id, False)
    return ok({"favorite": False}, processing_mode="deterministic")
