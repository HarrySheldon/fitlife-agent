"""Structured training context domain model (equipment, schedule, experience, injuries)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EquipmentId = Literal[
    "barbell",
    "dumbbell",
    "machine",
    "cable",
    "bodyweight",
    "kettlebell",
    "resistance_band",
    "cardio_machine",
]
ExperienceLevel = Literal["beginner", "intermediate", "advanced"]
PreferredSplit = Literal["auto", "full_body", "upper_lower", "push_pull_legs", "custom"]
InjuryArea = Literal["knee", "lower_back", "shoulder", "wrist", "elbow", "ankle", "hip", "neck", "other"]

EQUIPMENT_OPTIONS: tuple[EquipmentId, ...] = (
    "barbell",
    "dumbbell",
    "machine",
    "cable",
    "bodyweight",
    "kettlebell",
    "resistance_band",
    "cardio_machine",
)
EXPERIENCE_LEVELS: tuple[ExperienceLevel, ...] = ("beginner", "intermediate", "advanced")
PREFERRED_SPLITS: tuple[PreferredSplit, ...] = (
    "auto",
    "full_body",
    "upper_lower",
    "push_pull_legs",
    "custom",
)
INJURY_AREAS: tuple[InjuryArea, ...] = (
    "knee",
    "lower_back",
    "shoulder",
    "wrist",
    "elbow",
    "ankle",
    "hip",
    "neck",
    "other",
)


@dataclass(frozen=True)
class InjuryLimitation:
    area: str
    note: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"area": self.area, "note": self.note}


@dataclass(frozen=True)
class TrainingContext:
    user_id: str
    available_equipment: tuple[str, ...] = ("bodyweight", "dumbbell")
    weekly_available_days: int = 3
    session_duration_min: int = 45
    experience_level: ExperienceLevel = "beginner"
    preferred_split: PreferredSplit = "auto"
    injury_or_limitations: tuple[InjuryLimitation, ...] = ()
    notes: str = ""
    updated_at: str = ""
    configured: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "available_equipment": list(self.available_equipment),
            "weekly_available_days": self.weekly_available_days,
            "session_duration_min": self.session_duration_min,
            "experience_level": self.experience_level,
            "preferred_split": self.preferred_split,
            "injury_or_limitations": [item.to_dict() for item in self.injury_or_limitations],
            "notes": self.notes,
            "updated_at": self.updated_at,
            "configured": self.configured,
        }


def default_training_context(user_id: str) -> TrainingContext:
    return TrainingContext(user_id=user_id, configured=False)
