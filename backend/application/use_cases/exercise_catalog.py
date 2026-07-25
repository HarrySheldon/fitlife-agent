from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from backend.application.ports.exercise_catalog_repository import (
    ExerciseCatalogItem,
    ExerciseCatalogRepository,
    ExerciseCatalogRepositoryError,
    ExerciseDefinition,
    ExerciseType,
    NewCustomExercise,
)
from backend.domain.errors import ApplicationError


@dataclass(frozen=True)
class CustomExerciseCommand:
    name: str
    exercise_type: ExerciseType
    primary_muscle: str
    secondary_muscles: tuple[str, ...] = ()
    met: float | None = None
    aliases: tuple[str, ...] = ()


class ExerciseCatalogServiceError(ApplicationError):
    def __init__(self, code: str, *, status_code: int) -> None:
        super().__init__(
            code=code,
            message=code,
            status_code=status_code,
            processing_mode="deterministic",
        )


class ExerciseCatalogService:
    def __init__(
        self,
        repository: ExerciseCatalogRepository,
        *,
        mutation_scope: Callable[[str], AbstractContextManager] | None = None,
    ) -> None:
        self.repository = repository
        self._mutation_scope = mutation_scope or (lambda _user_id: nullcontext())

    def search(
        self,
        user_id: str,
        query: str,
        *,
        limit: int = 20,
    ) -> tuple[ExerciseCatalogItem, ...]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 50
        ):
            raise ExerciseCatalogServiceError(
                "EXERCISE_SEARCH_LIMIT_INVALID",
                status_code=422,
            )
        if not isinstance(query, str) or len(query) > 256:
            raise ExerciseCatalogServiceError(
                "EXERCISE_SEARCH_QUERY_INVALID",
                status_code=422,
            )
        return self.repository.search(user_id, query.strip(), limit=limit)

    def create_custom_exercise(
        self,
        user_id: str,
        command: CustomExerciseCommand,
    ) -> ExerciseCatalogItem:
        definition = _definition(command)
        with self._mutation_scope(user_id):
            try:
                return self.repository.create_custom_exercise(
                    user_id,
                    NewCustomExercise(
                        definition=definition,
                        aliases=command.aliases,
                    ),
                )
            except ExerciseCatalogRepositoryError as error:
                raise _repository_error(error) from None

    def set_favorite(
        self,
        user_id: str,
        exercise_id: str,
        favorite: bool,
    ) -> None:
        with self._mutation_scope(user_id):
            try:
                self.repository.set_favorite(user_id, exercise_id, favorite)
            except ExerciseCatalogRepositoryError as error:
                raise _repository_error(error) from None


def _definition(command: CustomExerciseCommand) -> ExerciseDefinition:
    name = _text(command.name, "EXERCISE_NAME_REQUIRED", 100)
    primary = _text(
        command.primary_muscle,
        "EXERCISE_PRIMARY_MUSCLE_REQUIRED",
        60,
    )
    if command.exercise_type not in {"strength", "cardio"}:
        raise ExerciseCatalogServiceError(
            "EXERCISE_TYPE_INVALID",
            status_code=422,
        )
    secondary = tuple(
        dict.fromkeys(
            _text(item, "EXERCISE_SECONDARY_MUSCLE_INVALID", 60)
            for item in command.secondary_muscles
        )
    )
    met = command.met
    if met is not None:
        try:
            value = Decimal(str(met))
        except (InvalidOperation, ValueError):
            value = Decimal("-1")
        if (
            isinstance(met, bool)
            or not isinstance(met, (int, float))
            or not value.is_finite()
            or value <= 0
        ):
            raise ExerciseCatalogServiceError(
                "EXERCISE_MET_INVALID",
                status_code=422,
            )
    return ExerciseDefinition(
        name=name,
        exercise_type=command.exercise_type,
        primary_muscle=primary,
        secondary_muscles=secondary,
        met=met,
        source="user_custom",
    )


def _text(value: object, code: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExerciseCatalogServiceError(code, status_code=422)
    normalized = value.strip()
    if len(normalized) > max_length:
        raise ExerciseCatalogServiceError(code, status_code=422)
    return normalized


def _repository_error(
    error: ExerciseCatalogRepositoryError,
) -> ExerciseCatalogServiceError:
    status = 404 if error.code == "EXERCISE_NOT_VISIBLE" else 422
    return ExerciseCatalogServiceError(error.code, status_code=status)
