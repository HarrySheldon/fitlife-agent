"""Scenario contracts for the business-task evaluation runner.

A scenario is declarative data, never executable code. It names a sequence of HTTP
calls against the public API and the final state that must hold. Nothing here imports
a file path or accepts a URL: the runner decides how to build the isolated environment
from the declared seed types.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal
from urllib.parse import unquote

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from backend.domain.profile_targets import SafetyCondition
from backend.api.meal_schemas import MealDraftMutationRequest
from backend.api.workout_schemas import WorkoutDraftMutationRequest
from typing import Annotated

ActorName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")]


class RecordSeeds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meals: list[MealDraftMutationRequest] = Field(default_factory=list, max_length=20)
    workouts: list[WorkoutDraftMutationRequest] = Field(default_factory=list, max_length=20)


class PlanSeeds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_count: int = Field(default=0, strict=True, ge=0, le=1)
    draft_count: int = Field(default=0, strict=True, ge=0, le=5)
    # A plan the scenario declares, rather than one the deterministic generator
    # produces. A patch names the exact element it replaces, so a candidate is
    # only writable against a base whose shape the scenario already knows: with a
    # generated plan every ``old_value`` would be a guess, and a guessed patch
    # fails for staleness instead of for the rule under test.
    document: dict[str, Any] | None = None
    plan_id: str = Field(default="plan-00000001", pattern=r"^plan-[a-f0-9]{8,64}$")
    activated_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def declared_document(self):
        if self.document is None:
            return self
        if self.active_count or self.draft_count:
            # Two sources for "the plan this account has" would make the head
            # depend on which one happened to be written last.
            raise ValueError("A declared plan document cannot be combined with generated plans")
        if not isinstance(self.document.get("workout_plan"), dict) or not isinstance(
                self.document.get("diet_plan"), dict):
            raise ValueError("A declared plan document must hold both plan domains")
        if set(self.document) - {"workout_plan", "diet_plan", "validation", "trace"}:
            raise ValueError("A declared plan document has an unknown top-level field")
        if len(json.dumps(self.document, ensure_ascii=False, allow_nan=False)) > 65536:
            raise ValueError("A declared plan document exceeds the maximum size")
        return self


class PlanConstraintSeed(BaseModel):
    """The versioned hard constraints a plan task is created against.

    Written through the same repository the setup form writes, because the whole
    safety argument of a plan task is that the values it was frozen with can be
    re-read from a version at confirmation time. Seeding them anywhere else would
    measure a deployment that cannot confirm anything.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    age: int = Field(ge=18, le=100)
    height_cm: float = Field(ge=120, le=230)
    weight_kg: float = Field(ge=30, le=300)
    energy_parameter: Literal["male", "female", "neutral"] = "neutral"
    activity_level: Literal["sedentary", "light", "moderate", "high"] = "moderate"
    goal: Literal["fat_loss", "muscle_gain", "maintenance"] = "fat_loss"
    calories: int = Field(ge=800, le=6000)
    carbs: int = Field(ge=0, le=1000)
    protein: int = Field(ge=20, le=400)
    fat: int = Field(ge=10, le=300)
    allergies_or_restrictions: list[str] = Field(default_factory=list, max_length=8)
    safety_conditions: list[SafetyCondition] = Field(default_factory=list, max_length=4)
    effective_from: AwareDatetime


class AuthorizationSeeds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    additional_users: list[ActorName] = Field(default_factory=list, max_length=5)

    @field_validator("additional_users")
    @classmethod
    def unique_actors(cls, value):
        if "primary" in value or len(value) != len(set(value)):
            raise ValueError("Additional actor names must be unique and not primary")
        return value


class FaultSeeds(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    expire_drafts: bool = False
    # Backdate stored chat messages immediately before the Nth step runs, so the
    # 90-day read window can be replayed without waiting three months.
    expire_coach_messages_at_step: int = Field(default=0, strict=True, ge=0, le=100)
    crash_worker: bool = False
    sleep_seconds: float = Field(default=0, ge=0, le=30)
    # Deterministic slow answer: cancellation and the single slot can only be
    # replayed reliably if generation does not finish before the next request.
    slow_coach_answer_seconds: float = Field(default=0, ge=0, le=10)
    # Deterministic output that breaks the answer length contract.
    oversize_coach_answer: bool = False
    # Declarative mock responses, not executable scripts or import paths.
    unified_decisions: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    poison_knowledge: bool = False
    unified_revoke_at_call: int = Field(default=0, strict=True, ge=0, le=16)
    unified_review_unavailable: bool = False


class ProfileSeed(BaseModel):
    """Synthetic profile fields; arbitrary keys are forbidden."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    height_cm: float | None = Field(default=None, ge=120, le=230)
    weight_kg: float | None = Field(default=None, ge=30, le=300)
    age: int | None = Field(default=None, ge=18, le=100)
    gender: Literal["male", "female", "other"] | None = None
    goal: Literal["fat_loss", "muscle_gain", "maintenance"] | None = None
    weekly_training_frequency: int | None = Field(default=None, ge=0, le=7)
    diet_preferences: list[str] = Field(default_factory=list)
    allergies_or_restrictions: list[str] = Field(default_factory=list)
    target_weight_kg: float | None = Field(default=None, ge=30, le=300)
    daily_calorie_target: int | None = Field(default=None, ge=800, le=6000)
    daily_protein_target: int | None = Field(default=None, ge=20, le=400)
    energy_parameter: Literal["male", "female", "neutral"] | None = None
    activity_level: Literal["sedentary", "light", "moderate", "high"] | None = None
    auto_target_disabled: bool = False
    safety_conditions: list[SafetyCondition] = Field(default_factory=list, max_length=4)
    effective_from: AwareDatetime | None = None


class FoodSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source_record_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    basis_type: Literal["per_100g", "per_100ml", "per_serving"] = "per_100g"
    basis_amount: float = Field(default=100, gt=0)
    unit: str = "g"
    calories: float = Field(ge=0)
    carbs: float = Field(ge=0)
    protein: float = Field(ge=0)
    fat: float = Field(ge=0)
    source_name: str = "task-eval-synthetic"
    dataset_version: str = "1"
    license: str = "synthetic"
    attribution: str = "task evaluation"
    provenance: dict[str, Any] = Field(default_factory=dict)


class ExerciseSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source_record_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    exercise_type: Literal["strength", "cardio"]
    primary_muscle: str = Field(min_length=1, max_length=200)
    secondary_muscles: list[str] = Field(default_factory=list, max_length=50)
    met: float | None = Field(default=None, gt=0)
    source_name: str = "task-eval-synthetic"
    dataset_version: str = "1"
    license: str = "synthetic"
    attribution: str = "task evaluation"
    provenance: dict[str, Any] = Field(default_factory=dict)


class CatalogSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The runner materialises these as catalog rows. They are structured data, not a
    # path to an arbitrary file on disk.
    foods: list[FoodSeed] = Field(default_factory=list, max_length=100)
    exercises: list[ExerciseSeed] = Field(default_factory=list, max_length=100)


class InitialState(BaseModel):
    """Declared seed types only.

    profile is a structured object, never a file path; the runner refuses arbitrary
    imports by construction because this type only holds the declared shapes.
    """

    model_config = ConfigDict(extra="forbid")

    profile: ProfileSeed | None = None
    catalog: CatalogSeed | None = None
    records: RecordSeeds = Field(default_factory=RecordSeeds)
    plans: PlanSeeds = Field(default_factory=PlanSeeds)
    # The versioned profile, goal, target and allergy rows a plan task reads its
    # hard constraints from. Separate from ``profile`` on purpose: that one drives
    # the setup form's own endpoint, and a plan scenario is not about the form.
    plan_constraints: PlanConstraintSeed | None = None
    authorization: AuthorizationSeeds = Field(default_factory=AuthorizationSeeds)
    faults: FaultSeeds = Field(default_factory=FaultSeeds)


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: ActorName = "primary"
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    body: dict[str, Any] | None = None
    # Literal header values. ``{name}`` references are resolved against captured
    # variables, so a version or id captured earlier can feed If-Match/Idempotency-Key.
    headers: dict[str, str | dict[str, str]] = Field(default_factory=dict)
    expected_status: int = Field(default=200, strict=True, ge=100, le=599)
    # Bounded GET-only polling, never retry an accepted generation POST.
    wait_for_turn: bool = Field(default=False, strict=True)
    # maps a returned field to a variable name, e.g. {"record_ids": "data.record_ids"}
    capture: dict[str, str] = Field(default_factory=dict)
    # maps a returned field to an observed key, feeding the final expected comparison
    observe: dict[str, str] = Field(default_factory=dict)
    # maps a missing-field name to the scripted user answer
    answer_by_field: dict[str, Any] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def local_path(cls, value):
        decoded = unquote(value)
        if (len(value) > 2048 or not decoded.startswith("/") or decoded.startswith("//")
                or "\\" in decoded or ":" in decoded or "#" in decoded
                or any(ord(char) < 32 or ord(char) == 127 for char in decoded)
                or any(part in {".", ".."} for part in decoded.split("?")[0].split("/"))):
            raise ValueError("A scenario step must use a local relative API path")
        return value

    @model_validator(mode="after")
    def valid_data(self):
        if self.wait_for_turn and (self.method != "GET" or self.expected_status != 200
                or not re.fullmatch(r"/api/v1/coach/turns/[A-Za-z0-9_{}-]+", self.path)
                or self.body):
            raise ValueError("Turn waiting requires a read-only successful status request")
        def inspect(value, depth=0):
            if depth > 30:
                raise ValueError("Scenario data exceeds maximum nesting")
            if isinstance(value, dict):
                if "$ref" in value:
                    if set(value) != {"$ref"} or not isinstance(value["$ref"], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value["$ref"]):
                        raise ValueError("Invalid structured variable reference")
                for child in value.values():
                    inspect(child, depth + 1)
            elif isinstance(value, list):
                for child in value:
                    inspect(child, depth + 1)
        inspect(self.body)
        inspect(self.headers)
        for value in self.headers.values():
            if isinstance(value, dict) and set(value) != {"$ref"}:
                raise ValueError("Dictionary header values must be structured variable references")
        inspect(self.answer_by_field)
        for mapping in (self.capture, self.observe):
            if len(mapping) > 100 or any(not key or not path or any(not part for part in path.split(".")) for key, path in mapping.items()):
                raise ValueError("Invalid capture or observation mapping")
        if len(json.dumps(self.model_dump(mode="json"), allow_nan=False)) > 65536:
            raise ValueError("Step exceeds maximum data size")
        return self


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    version: int = Field(strict=True, gt=0)
    initial_state: InitialState = Field(default_factory=InitialState)
    steps: list[Step] = Field(default_factory=list, max_length=100)
    expected: dict[str, Any] = Field(default_factory=dict)
    requires: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def bounded_data(self):
        if len(json.dumps(self.model_dump(mode="json"), allow_nan=False)) > 1048576:
            raise ValueError("Scenario exceeds maximum data size")
        return self


class Suite(BaseModel):
    """Validate the entire synthetic suite before any case executes."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    scenarios: list[Scenario] = Field(max_length=100)

    @field_validator("schema_version", mode="before")
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported suite schema version")
        return value

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [scenario.id for scenario in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("Suite scenario IDs must be unique")
        return self
