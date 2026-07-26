from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from backend.application.ports.exercise_catalog_repository import ExerciseType
from backend.domain.workouts import Intensity, StrengthSet


class WorkoutRepositoryError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CustomExerciseSnapshot:
    name: str
    exercise_type: ExerciseType
    primary_muscle: str
    secondary_muscles: tuple[str, ...]
    met: float | None


@dataclass(frozen=True)
class StrengthExerciseInput:
    sets: tuple[StrengthSet, ...]
    catalog_exercise_id: str | None = None
    custom_exercise: CustomExerciseSnapshot | None = None


@dataclass(frozen=True)
class CardioItemInput:
    duration_min: float
    device_calories: float | None
    catalog_exercise_id: str | None = None
    custom_exercise: CustomExerciseSnapshot | None = None


@dataclass(frozen=True)
class WorkoutDraftInput:
    log_date: str
    title: str
    started_at: str | None
    duration_min: float | None
    intensity: Intensity | None
    entry_method: Literal["form"]
    strength_exercises: tuple[StrengthExerciseInput, ...]
    cardio_items: tuple[CardioItemInput, ...]
    recovery_state: dict[str, object] | None = None


@dataclass(frozen=True)
class StrengthExerciseSnapshot:
    catalog_exercise_id: str | None
    exercise_name: str
    primary_muscle: str
    secondary_muscles: tuple[str, ...]
    sets: tuple[StrengthSet, ...]
    provenance: dict[str, object]
    custom_exercise: CustomExerciseSnapshot | None = None


@dataclass(frozen=True)
class CardioItemSnapshot:
    catalog_exercise_id: str | None
    activity_name: str
    primary_muscle: str
    secondary_muscles: tuple[str, ...]
    duration_min: float
    device_calories: float | None
    met: float | None
    estimated_calories: float
    is_estimate: bool
    estimate: dict[str, object]
    provenance: dict[str, object]
    custom_exercise: CustomExerciseSnapshot | None = None


@dataclass(frozen=True)
class WorkoutDraftPayload:
    log_date: str
    title: str
    started_at: str | None
    duration_min: float | None
    intensity: Intensity | None
    entry_method: Literal["form"]
    weight_kg_snapshot: float
    estimated_calories: float | None
    estimate: dict[str, object]
    strength_exercises: tuple[StrengthExerciseSnapshot, ...]
    cardio_items: tuple[CardioItemSnapshot, ...]
    recovery_state: dict[str, object] | None = None


@dataclass(frozen=True)
class WorkoutDraft:
    id: str
    user_id: str
    payload: WorkoutDraftPayload
    version: int
    expires_at: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ConfirmedWorkout:
    id: str
    user_id: str
    log_date: str
    title: str
    started_at: str | None
    duration_min: float | None
    intensity: Intensity | None
    entry_method: str
    weight_kg_snapshot: float
    estimated_calories: float | None
    estimate: dict[str, object]
    strength_exercises: tuple[StrengthExerciseSnapshot, ...]
    cardio_items: tuple[CardioItemSnapshot, ...]
    created_at: str
    updated_at: str
    replayed: bool = False


@runtime_checkable
class WorkoutRepository(Protocol):
    def create_draft(
        self,
        user_id: str,
        payload: WorkoutDraftInput,
        expires_at: str,
    ) -> WorkoutDraft: ...

    def get_draft(
        self,
        user_id: str,
        draft_id: str,
    ) -> WorkoutDraft | None: ...

    def find_latest_draft(
        self,
        user_id: str,
        log_date: str,
    ) -> WorkoutDraft | None: ...

    def update_draft(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        payload: WorkoutDraftInput,
    ) -> WorkoutDraft: ...

    def delete_draft(self, user_id: str, draft_id: str) -> None: ...

    def confirm(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        request_fingerprint: str,
        timezone_name: str = "UTC",
    ) -> ConfirmedWorkout: ...

    def list_sessions(
        self,
        user_id: str,
        log_date: str,
    ) -> tuple[ConfirmedWorkout, ...]: ...
