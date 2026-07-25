from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


MuscleName = Annotated[str, Field(min_length=1, max_length=60)]
ExerciseAlias = Annotated[str, Field(min_length=1, max_length=100)]


class CustomExerciseValuesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    exercise_type: Literal["strength", "cardio"]
    primary_muscle: str = Field(min_length=1, max_length=60)
    secondary_muscles: list[MuscleName] = Field(
        default_factory=list,
        max_length=20,
    )
    met: float | None = Field(default=None, gt=0)


class CustomExerciseRequest(CustomExerciseValuesRequest):
    aliases: list[ExerciseAlias] = Field(default_factory=list, max_length=20)


class StrengthSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_number: int = Field(ge=1, le=100)
    reps: int = Field(ge=1, le=1000)
    load_kg: float | None = Field(default=None, ge=0, le=2000)
    bodyweight: bool = False


class StrengthExerciseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_exercise_id: str | None = Field(default=None, min_length=1)
    custom_exercise: CustomExerciseValuesRequest | None = None
    sets: list[StrengthSetRequest] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_one_source(self):
        if (self.catalog_exercise_id is None) == (
            self.custom_exercise is None
        ):
            raise ValueError("exactly one exercise source is required")
        return self


class CardioItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_exercise_id: str | None = Field(default=None, min_length=1)
    custom_exercise: CustomExerciseValuesRequest | None = None
    duration_min: float = Field(gt=0, le=1440)
    device_calories: float | None = Field(default=None, ge=0, le=10000)

    @model_validator(mode="after")
    def require_one_source(self):
        if (self.catalog_exercise_id is None) == (
            self.custom_exercise is None
        ):
            raise ValueError("exactly one exercise source is required")
        return self


class WorkoutDraftMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    log_date: date
    title: str = Field(min_length=1, max_length=100)
    started_at: datetime | None = None
    duration_min: float | None = Field(default=None, gt=0, le=1440)
    intensity: Literal["low", "medium", "high"] | None = None
    entry_method: Literal["form"] = "form"
    strength_exercises: list[StrengthExerciseRequest] = Field(
        default_factory=list,
        max_length=50,
    )
    cardio_items: list[CardioItemRequest] = Field(
        default_factory=list,
        max_length=50,
    )


class StrengthSetResponse(BaseModel):
    set_number: int
    reps: int
    load_kg: float | None
    bodyweight: bool


class CustomExerciseResponse(BaseModel):
    name: str
    exercise_type: Literal["strength", "cardio"]
    primary_muscle: str
    secondary_muscles: list[str]
    met: float | None


class StrengthExerciseResponse(BaseModel):
    catalog_exercise_id: str | None
    exercise_name: str
    primary_muscle: str
    secondary_muscles: list[str]
    sets: list[StrengthSetResponse]
    provenance: dict[str, Any]
    custom_exercise: CustomExerciseResponse | None


class CardioItemResponse(BaseModel):
    catalog_exercise_id: str | None
    activity_name: str
    primary_muscle: str
    secondary_muscles: list[str]
    duration_min: float
    device_calories: float | None
    met: float | None
    estimated_calories: float
    is_estimate: bool
    estimate: dict[str, Any]
    provenance: dict[str, Any]
    custom_exercise: CustomExerciseResponse | None


class WorkoutDraftPayloadResponse(BaseModel):
    log_date: str
    title: str
    started_at: str | None
    duration_min: float | None
    intensity: Literal["low", "medium", "high"] | None
    entry_method: str
    weight_kg_snapshot: float
    estimated_calories: float | None
    estimate: dict[str, Any]
    strength_exercises: list[StrengthExerciseResponse]
    cardio_items: list[CardioItemResponse]


class WorkoutDraftResponse(BaseModel):
    id: str
    user_id: str
    payload: WorkoutDraftPayloadResponse
    version: int
    expires_at: str
    created_at: str
    updated_at: str


class ConfirmedWorkoutResponse(BaseModel):
    id: str
    user_id: str
    log_date: str
    title: str
    started_at: str | None
    duration_min: float | None
    intensity: Literal["low", "medium", "high"] | None
    entry_method: str
    weight_kg_snapshot: float
    estimated_calories: float | None
    estimate: dict[str, Any]
    strength_exercises: list[StrengthExerciseResponse]
    cardio_items: list[CardioItemResponse]
    created_at: str
    updated_at: str
    replayed: bool


class ExerciseCatalogItemResponse(BaseModel):
    id: str
    owner_user_id: str | None
    source: str
    source_name: str
    source_record_id: str
    dataset_version: str | None
    name: str
    exercise_type: Literal["strength", "cardio"]
    primary_muscle: str
    secondary_muscles: list[str]
    met: float | None
    license: str | None
    attribution: str | None
    provenance: dict[str, Any]
    content_hash: str | None
    active: bool
    aliases: list[str]
    is_favorite: bool
    use_count: int
    last_used_at: str | None
    rank_group: int


class FavoriteResponse(BaseModel):
    favorite: bool


class DeletedResponse(BaseModel):
    deleted: bool
