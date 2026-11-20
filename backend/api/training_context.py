"""API routes for structured user training context."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from backend.api.dependencies import require_current_user
from backend.api.utils import ok
from backend.domain.training_context import (
    EQUIPMENT_OPTIONS,
    EXPERIENCE_LEVELS,
    INJURY_AREAS,
    PREFERRED_SPLITS,
    EquipmentId,
    ExperienceLevel,
    InjuryArea,
    InjuryLimitation,
    PreferredSplit,
)
from backend.infrastructure.repositories.sqlite_training_context_repository import (
    SQLiteTrainingContextRepository,
)
from backend.infrastructure.sqlite.runtime import get_database
from backend.schemas import AuthenticatedUser

router = APIRouter(prefix="/api/v1/training-context")


class InjuryLimitationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area: InjuryArea
    note: str = Field(default="", max_length=200)


class TrainingContextUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available_equipment: list[EquipmentId] = Field(min_length=1, max_length=16)
    weekly_available_days: int = Field(ge=1, le=7)
    session_duration_min: int = Field(ge=15, le=180)
    experience_level: ExperienceLevel
    preferred_split: PreferredSplit = "auto"
    injury_or_limitations: list[InjuryLimitationInput] = Field(default_factory=list, max_length=12)
    notes: str = Field(default="", max_length=500)


def get_training_context_repo() -> SQLiteTrainingContextRepository:
    return SQLiteTrainingContextRepository(get_database())


@router.get("")
def get_training_context(
    user: AuthenticatedUser = Depends(require_current_user),
    repo: SQLiteTrainingContextRepository = Depends(get_training_context_repo),
):
    context = repo.get(user.user_id)
    return ok(
        {
            "training_context": context.to_dict(),
            "options": {
                "equipment": list(EQUIPMENT_OPTIONS),
                "experience_levels": list(EXPERIENCE_LEVELS),
                "preferred_splits": list(PREFERRED_SPLITS),
                "injury_areas": list(INJURY_AREAS),
            },
        },
        processing_mode="deterministic",
    )


@router.put("")
def update_training_context(
    payload: TrainingContextUpdateRequest,
    user: AuthenticatedUser = Depends(require_current_user),
    repo: SQLiteTrainingContextRepository = Depends(get_training_context_repo),
):
    saved = repo.upsert(
        user.user_id,
        available_equipment=payload.available_equipment,
        weekly_available_days=payload.weekly_available_days,
        session_duration_min=payload.session_duration_min,
        experience_level=payload.experience_level,
        preferred_split=payload.preferred_split,
        injury_or_limitations=[
            InjuryLimitation(area=item.area, note=item.note)
            for item in payload.injury_or_limitations
        ],
        notes=payload.notes,
    )
    return ok(
        {"training_context": saved.to_dict()},
        processing_mode="deterministic",
    )
