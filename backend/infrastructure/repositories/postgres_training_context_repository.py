"""PostgreSQL repository for structured user training context."""
from __future__ import annotations

from datetime import datetime, timezone
import json

from backend.domain.training_context import (
    EQUIPMENT_OPTIONS,
    EXPERIENCE_LEVELS,
    INJURY_AREAS,
    PREFERRED_SPLITS,
    InjuryLimitation,
    TrainingContext,
    default_training_context,
)
from backend.infrastructure.postgres.database import PostgresDatabase


class PostgresTrainingContextRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def get(self, user_id: str) -> TrainingContext:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT user_id, available_equipment_json, weekly_available_days,
                       session_duration_min, experience_level, preferred_split,
                       injury_or_limitations_json, notes, updated_at
                FROM user_training_context
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return default_training_context(user_id)
        equipment_raw = json.loads(row["available_equipment_json"] or "[]")
        injuries_raw = json.loads(row["injury_or_limitations_json"] or "[]")
        injuries = tuple(
            InjuryLimitation(area=str(item.get("area", "other")), note=str(item.get("note", "")))
            for item in injuries_raw
            if isinstance(item, dict) and item.get("area")
        )
        return TrainingContext(
            user_id=row["user_id"],
            available_equipment=tuple(str(item) for item in equipment_raw if isinstance(item, str)),
            weekly_available_days=int(row["weekly_available_days"]),
            session_duration_min=int(row["session_duration_min"]),
            experience_level=row["experience_level"],
            preferred_split=row["preferred_split"],
            injury_or_limitations=injuries,
            notes=row["notes"] or "",
            updated_at=row["updated_at"] or "",
            configured=True,
        )

    def upsert(
        self,
        user_id: str,
        *,
        available_equipment: list[str] | tuple[str, ...],
        weekly_available_days: int,
        session_duration_min: int,
        experience_level: str,
        preferred_split: str,
        injury_or_limitations: list[InjuryLimitation] | tuple[InjuryLimitation, ...],
        notes: str = "",
    ) -> TrainingContext:
        valid_equipment = tuple(dict.fromkeys(eq for eq in available_equipment if eq in EQUIPMENT_OPTIONS))
        if not valid_equipment:
            valid_equipment = ("bodyweight",)
        if experience_level not in EXPERIENCE_LEVELS:
            raise ValueError(f"Unsupported experience_level: {experience_level}")
        if preferred_split not in PREFERRED_SPLITS:
            raise ValueError(f"Unsupported preferred_split: {preferred_split}")
        cleaned_injuries = tuple(
            InjuryLimitation(
                area=item.area if item.area in INJURY_AREAS else "other",
                note=item.note.strip()[:200],
            )
            for item in injury_or_limitations
        )
        now = datetime.now(timezone.utc).isoformat()
        cleaned_notes = notes.strip()[:500]
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO user_training_context (
                    user_id, available_equipment_json, weekly_available_days,
                    session_duration_min, experience_level, preferred_split,
                    injury_or_limitations_json, notes, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    available_equipment_json = excluded.available_equipment_json,
                    weekly_available_days = excluded.weekly_available_days,
                    session_duration_min = excluded.session_duration_min,
                    experience_level = excluded.experience_level,
                    preferred_split = excluded.preferred_split,
                    injury_or_limitations_json = excluded.injury_or_limitations_json,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    json.dumps(list(valid_equipment), ensure_ascii=False),
                    int(weekly_available_days),
                    int(session_duration_min),
                    experience_level,
                    preferred_split,
                    json.dumps([item.to_dict() for item in cleaned_injuries], ensure_ascii=False),
                    cleaned_notes,
                    now,
                ),
            )
        return TrainingContext(
            user_id=user_id,
            available_equipment=valid_equipment,
            weekly_available_days=int(weekly_available_days),
            session_duration_min=int(session_duration_min),
            experience_level=experience_level,  # type: ignore[arg-type]
            preferred_split=preferred_split,  # type: ignore[arg-type]
            injury_or_limitations=cleaned_injuries,
            notes=cleaned_notes,
            updated_at=now,
            configured=True,
        )
