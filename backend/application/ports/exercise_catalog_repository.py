from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


ExerciseType = Literal["strength", "cardio"]
ExerciseSource = Literal[
    "public",
    "user_custom",
    "agent_estimate",
    "legacy_import",
]


class ExerciseCatalogRepositoryError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ExerciseDefinition:
    name: str
    exercise_type: ExerciseType
    primary_muscle: str
    secondary_muscles: tuple[str, ...]
    met: float | None
    source: ExerciseSource


@dataclass(frozen=True)
class ExerciseCatalogItem:
    id: str
    owner_user_id: str | None
    source: ExerciseSource
    source_name: str
    source_record_id: str
    dataset_version: str | None
    name: str
    exercise_type: ExerciseType
    primary_muscle: str
    secondary_muscles: tuple[str, ...]
    met: float | None
    license: str | None
    attribution: str | None
    provenance: dict[str, object]
    content_hash: str | None
    active: bool
    aliases: tuple[str, ...]
    is_favorite: bool
    use_count: int
    last_used_at: str | None
    rank_group: int


@dataclass(frozen=True)
class NewCustomExercise:
    definition: ExerciseDefinition
    aliases: tuple[str, ...] = ()


@runtime_checkable
class ExerciseCatalogRepository(Protocol):
    def search(
        self,
        user_id: str,
        query: str,
        *,
        limit: int,
    ) -> tuple[ExerciseCatalogItem, ...]: ...

    def create_custom_exercise(
        self,
        user_id: str,
        exercise: NewCustomExercise,
    ) -> ExerciseCatalogItem: ...

    def set_favorite(
        self,
        user_id: str,
        exercise_id: str,
        favorite: bool,
    ) -> None: ...

    def record_usage(self, user_id: str, exercise_id: str) -> None: ...
