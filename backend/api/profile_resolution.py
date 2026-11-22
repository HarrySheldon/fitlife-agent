"""Authoritative profile & target resolution across SQLite setup and legacy file projection."""
from __future__ import annotations

from dataclasses import dataclass

from backend.domain.plan_cycles import GoalType
from backend.infrastructure.repositories.sqlite_profile_target_repository import (
    SQLiteProfileTargetRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.schemas import UserProfile
from backend.tools.data_access import DEFAULT_PROFILE


@dataclass(frozen=True)
class ResolvedProfileContext:
    goal: GoalType
    calorie_target: float
    protein_target: float
    target_weight_kg: float | None
    has_sqlite_setup: bool
    is_synthetic_default: bool


def resolve_authoritative_profile_context(
    db: SQLiteDatabase,
    user_id: str,
    legacy_profile: UserProfile,
) -> ResolvedProfileContext:
    """Resolve user goals, nutrition targets, and target weight without stale defaults.

    Legacy ``user_profile.json`` files are seeded with ``DEFAULT_PROFILE``
    (``target_weight_kg=68.0``, ``weekly_training_frequency=4``), and modern
    SQLite onboarding only projects a subset of fields back to that JSON.
    """
    setup = SQLiteProfileTargetRepository(db).get_setup(user_id)
    has_sqlite_setup = any(
        part is not None for part in (setup.profile, setup.goal, setup.target)
    )
    is_synthetic_default = legacy_profile == DEFAULT_PROFILE

    if setup.goal is not None and setup.goal.goal in (
        "fat_loss",
        "muscle_gain",
        "maintenance",
    ):
        goal: GoalType = setup.goal.goal  # type: ignore[assignment]
    elif legacy_profile.goal in ("fat_loss", "muscle_gain", "maintenance"):
        goal = legacy_profile.goal  # type: ignore[assignment]
    else:
        goal = "maintenance"

    calorie_target = (
        float(setup.target.calories)
        if setup.target is not None
        else float(legacy_profile.daily_calorie_target or 0)
    )
    protein_target = (
        float(setup.target.protein)
        if setup.target is not None
        else float(legacy_profile.daily_protein_target or 0)
    )

    if setup.goal is not None and setup.goal.goal == "maintenance":
        target_weight_kg: float | None = None
    elif (
        has_sqlite_setup
        and legacy_profile.target_weight_kg is not None
        and DEFAULT_PROFILE.target_weight_kg is not None
        and float(legacy_profile.target_weight_kg) == float(DEFAULT_PROFILE.target_weight_kg)
    ):
        target_weight_kg = None
    else:
        target_weight_kg = (
            float(legacy_profile.target_weight_kg)
            if legacy_profile.target_weight_kg
            else None
        )

    return ResolvedProfileContext(
        goal=goal,
        calorie_target=calorie_target,
        protein_target=protein_target,
        target_weight_kg=target_weight_kg,
        has_sqlite_setup=has_sqlite_setup,
        is_synthetic_default=is_synthetic_default,
    )
