from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


EnergyParameter = Literal["male", "female", "neutral"]
ActivityLevel = Literal["sedentary", "light", "moderate", "high"]
OverallGoal = Literal["fat_loss", "maintenance", "muscle_gain"]
TargetSource = Literal["deterministic_calculation", "manual", "agent_confirmed"]


class ProfileTargetRepositoryError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ProfileVersionInput:
    age: int
    height_cm: float
    weight_kg: float
    energy_parameter: EnergyParameter
    activity_level: ActivityLevel
    auto_target_disabled: bool
    safety_conditions: tuple[str, ...]
    effective_from: str


@dataclass(frozen=True)
class ProfileVersion(ProfileVersionInput):
    id: str
    user_id: str
    created_at: str


@dataclass(frozen=True)
class GoalVersionInput:
    goal: OverallGoal
    effective_from: str


@dataclass(frozen=True)
class GoalVersion(GoalVersionInput):
    id: str
    user_id: str
    created_at: str


@dataclass(frozen=True)
class TargetVersionInput:
    profile_version_id: str | None
    overall_goal_version_id: str | None
    calories: float
    carbs: float
    protein: float
    fat: float
    source: TargetSource
    formula_version: str | None
    rationale: dict[str, object]
    effective_from: str


@dataclass(frozen=True)
class TargetVersion(TargetVersionInput):
    id: str
    user_id: str
    created_at: str


@dataclass(frozen=True)
class ProfileTargetSetup:
    profile: ProfileVersion | None
    goal: GoalVersion | None
    target: TargetVersion | None


@runtime_checkable
class ProfileTargetRepository(Protocol):
    def get_setup(self, user_id: str) -> ProfileTargetSetup: ...

    def get_latest_profile(self, user_id: str) -> ProfileVersion | None: ...

    def get_latest_goal(self, user_id: str) -> GoalVersion | None: ...

    def get_latest_target(self, user_id: str) -> TargetVersion | None: ...

    def append_profile(
        self,
        user_id: str,
        profile: ProfileVersionInput,
    ) -> ProfileVersion: ...

    def append_goal(
        self,
        user_id: str,
        goal: GoalVersionInput,
    ) -> GoalVersion: ...

    def append_target(
        self,
        user_id: str,
        target: TargetVersionInput,
    ) -> TargetVersion: ...

    def list_targets(self, user_id: str) -> tuple[TargetVersion, ...]: ...

    def bootstrap(
        self,
        user_id: str,
        profile: ProfileVersionInput,
        goal: GoalVersionInput,
    ) -> ProfileTargetSetup: ...

    def confirm_target_once(
        self,
        user_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        target: TargetVersionInput,
    ) -> TargetVersion: ...

    def delete_user_data(self, user_id: str) -> None: ...
