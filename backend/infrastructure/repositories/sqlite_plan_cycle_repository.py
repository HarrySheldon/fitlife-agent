"""SQLite repository for periodized plan cycles and daily training schedules."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from uuid import uuid4

from backend.domain.plan_cycles import (
    CatalogExerciseOption,
    CyclePhase,
    PlanCycle,
    PlanDay,
    PrescribedExercise,
    compute_day_adherence,
    monday_of_week,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase


class SQLitePlanCycleRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def load_catalog_options(self, user_id: str) -> tuple[CatalogExerciseOption, ...]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT id, name, exercise_type, primary_muscle, provenance_json
                FROM exercise_catalog
                WHERE active = 1
                  AND (owner_user_id IS NULL OR owner_user_id = ?)
                ORDER BY CASE WHEN owner_user_id = ? THEN 0 ELSE 1 END, id ASC
                """,
                (user_id, user_id),
            ).fetchall()
        options: list[CatalogExerciseOption] = []
        for row in rows:
            prov: dict[str, object] = {}
            try:
                parsed = json.loads(row["provenance_json"] or "{}")
                if isinstance(parsed, dict):
                    prov = parsed
            except json.JSONDecodeError:
                pass
            options.append(
                CatalogExerciseOption(
                    id=row["id"],
                    name=row["name"],
                    exercise_type="cardio" if row["exercise_type"] == "cardio" else "strength",
                    primary_muscle=row["primary_muscle"] or "full_body",
                    equipment=str(prov.get("equipment") or ""),
                    mechanic=str(prov.get("mechanic") or ""),
                    level=str(prov.get("level") or "beginner"),
                )
            )
        return tuple(options)

    def create_draft(
        self,
        user_id: str,
        cycle_payload: dict[str, object],
        days_payload: list[dict[str, object]],
    ) -> PlanCycle:
        now = datetime.now(timezone.utc).isoformat()
        cycle_id = f"cycle-{uuid4().hex[:12]}"
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO plan_cycles (
                    id, user_id, title, goal_type, start_date, duration_weeks,
                    phases_json, status, source, rationale_json, version,
                    created_at, updated_at, activated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, 1, ?, ?, NULL)
                """,
                (
                    cycle_id,
                    user_id,
                    str(cycle_payload["title"]),
                    str(cycle_payload["goal_type"]),
                    str(cycle_payload["start_date"]),
                    int(cycle_payload["duration_weeks"]),
                    json.dumps(cycle_payload.get("phases", []), ensure_ascii=False),
                    str(cycle_payload.get("source", "deterministic")),
                    json.dumps(cycle_payload.get("rationale", {}), ensure_ascii=False),
                    now,
                    now,
                ),
            )
            for day in days_payload:
                day_id = f"pday-{uuid4().hex[:12]}"
                connection.execute(
                    """
                    INSERT INTO plan_days (
                        id, cycle_id, user_id, week_index, day_of_week, scheduled_date,
                        day_type, focus, estimated_duration_min, prescribed_exercises_json,
                        nutrition_override_json, status_override, notes, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                    """,
                    (
                        day_id,
                        cycle_id,
                        user_id,
                        int(day["week_index"]),
                        int(day["day_of_week"]),
                        str(day["scheduled_date"]),
                        str(day["day_type"]),
                        str(day.get("focus", "")),
                        day.get("estimated_duration_min"),
                        json.dumps(day.get("prescribed_exercises", []), ensure_ascii=False),
                        json.dumps(day.get("nutrition_override", {}), ensure_ascii=False),
                        str(day.get("notes", "")),
                        now,
                        now,
                    ),
                )
        created = self.get_cycle(user_id, cycle_id)
        assert created is not None
        return created

    def activate_cycle(self, user_id: str, cycle_id: str) -> PlanCycle | None:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT id, status FROM plan_cycles WHERE user_id = ? AND id = ?",
                (user_id, cycle_id),
            ).fetchone()
            if existing is None:
                return None
            connection.execute(
                """
                UPDATE plan_cycles
                SET status = 'archived', updated_at = ?, version = version + 1
                WHERE user_id = ? AND status = 'active' AND id != ?
                """,
                (now, user_id, cycle_id),
            )
            connection.execute(
                """
                UPDATE plan_cycles
                SET status = 'active', activated_at = ?, updated_at = ?, version = version + 1
                WHERE user_id = ? AND id = ?
                """,
                (now, now, user_id, cycle_id),
            )
        return self.get_cycle(user_id, cycle_id)

    def discard_draft(self, user_id: str, cycle_id: str) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM plan_cycles WHERE user_id = ? AND id = ? AND status = 'draft'",
                (user_id, cycle_id),
            )
        return cursor.rowcount > 0

    def list_cycles(self, user_id: str) -> tuple[PlanCycle, ...]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM plan_cycles
                WHERE user_id = ?
                ORDER BY
                    CASE status WHEN 'active' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END,
                    updated_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
        return tuple(_row_to_cycle(row) for row in rows)

    def get_cycle(self, user_id: str, cycle_id: str) -> PlanCycle | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM plan_cycles WHERE user_id = ? AND id = ?",
                (user_id, cycle_id),
            ).fetchone()
        return _row_to_cycle(row) if row is not None else None

    def get_active_cycle(self, user_id: str) -> PlanCycle | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM plan_cycles
                WHERE user_id = ? AND status = 'active'
                ORDER BY activated_at DESC, updated_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        return _row_to_cycle(row) if row is not None else None

    def get_cycle_days(
        self,
        user_id: str,
        cycle_id: str,
        *,
        week_index: int | None = None,
    ) -> tuple[PlanDay, ...]:
        params: list[object] = [user_id, cycle_id]
        sql = "SELECT * FROM plan_days WHERE user_id = ? AND cycle_id = ?"
        if week_index is not None:
            sql += " AND week_index = ?"
            params.append(week_index)
        sql += " ORDER BY week_index ASC, day_of_week ASC"
        with self.database.connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return tuple(_row_to_day(row) for row in rows)

    def get_day(self, user_id: str, day_id: str) -> PlanDay | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM plan_days WHERE user_id = ? AND id = ?",
                (user_id, day_id),
            ).fetchone()
        return _row_to_day(row) if row is not None else None

    def get_active_day_for_date(self, user_id: str, scheduled_date: str) -> tuple[PlanCycle, PlanDay] | None:
        active = self.get_active_cycle(user_id)
        if active is None:
            return None
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM plan_days
                WHERE user_id = ? AND cycle_id = ? AND scheduled_date = ?
                LIMIT 1
                """,
                (user_id, active.id, scheduled_date),
            ).fetchone()
        if row is None:
            return None
        return active, _row_to_day(row)

    def update_day(
        self,
        user_id: str,
        day_id: str,
        *,
        focus: str | None = None,
        day_type: str | None = None,
        status_override: object = ...,
        prescribed_exercises: list[dict[str, object]] | None = None,
        notes: str | None = None,
    ) -> PlanDay | None:
        current = self.get_day(user_id, day_id)
        if current is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        next_focus = current.focus if focus is None else focus.strip()[:120]
        next_day_type = current.day_type if day_type is None else day_type
        next_status_override = current.status_override if status_override is ... else status_override
        next_exercises_json = (
            json.dumps([ex.to_dict() for ex in current.prescribed_exercises], ensure_ascii=False)
            if prescribed_exercises is None
            else json.dumps(prescribed_exercises, ensure_ascii=False)
        )
        next_notes = current.notes if notes is None else notes.strip()[:400]
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE plan_days
                SET focus = ?, day_type = ?, status_override = ?,
                    prescribed_exercises_json = ?, notes = ?, updated_at = ?
                WHERE user_id = ? AND id = ?
                """,
                (
                    next_focus,
                    next_day_type,
                    next_status_override,
                    next_exercises_json,
                    next_notes,
                    now,
                    user_id,
                    day_id,
                ),
            )
        return self.get_day(user_id, day_id)

    def logged_workout_counts_by_date(
        self,
        user_id: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, int]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT log_date, COUNT(*) AS cnt
                FROM training_sessions
                WHERE user_id = ? AND log_date >= ? AND log_date <= ?
                GROUP BY log_date
                """,
                (user_id, start_date, end_date),
            ).fetchall()
        return {row["log_date"]: int(row["cnt"]) for row in rows}

    def week_adherence_summary(self, user_id: str, anchor_date_iso: str) -> dict[str, int] | None:
        active = self.get_active_cycle(user_id)
        if active is None:
            return None
        anchor = date.fromisoformat(anchor_date_iso)
        start = monday_of_week(anchor)
        end = start + timedelta(days=6)
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM plan_days
                WHERE user_id = ? AND cycle_id = ?
                  AND scheduled_date >= ? AND scheduled_date <= ?
                ORDER BY scheduled_date ASC
                """,
                (user_id, active.id, start.isoformat(), end.isoformat()),
            ).fetchall()
        if not rows:
            return None
        days = tuple(_row_to_day(row) for row in rows)
        logged = self.logged_workout_counts_by_date(user_id, start.isoformat(), end.isoformat())
        planned = 0
        completed = 0
        missed = 0
        skipped = 0
        for day in days:
            status, _ = compute_day_adherence(day, logged_workout_dates=logged, today_iso=anchor_date_iso)
            if status == "skipped":
                skipped += 1
            elif status == "rest":
                continue
            else:
                planned += 1
                if status == "completed":
                    completed += 1
                elif status == "missed":
                    missed += 1
        pct = min(100, round(completed * 100 / planned)) if planned > 0 else 100
        return {
            "completed": completed,
            "planned": planned,
            "missed": missed,
            "skipped": skipped,
            "pct": pct,
        }


def _row_to_cycle(row) -> PlanCycle:
    phases_raw = json.loads(row["phases_json"] or "[]")
    phases = tuple(
        CyclePhase(
            name=str(item.get("name", "")),
            start_week=int(item.get("start_week", 1)),
            end_week=int(item.get("end_week", 1)),
            focus=str(item.get("focus", "")),
            volume_multiplier=float(item.get("volume_multiplier", 1.0)),
        )
        for item in phases_raw
        if isinstance(item, dict)
    )
    rationale = json.loads(row["rationale_json"] or "{}")
    return PlanCycle(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        goal_type=row["goal_type"],
        start_date=row["start_date"],
        duration_weeks=int(row["duration_weeks"]),
        phases=phases,
        status=row["status"],
        source=row["source"],
        rationale=rationale if isinstance(rationale, dict) else {},
        version=int(row["version"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        activated_at=row["activated_at"],
    )


def _row_to_day(row) -> PlanDay:
    exercises_raw = json.loads(row["prescribed_exercises_json"] or "[]")
    exercises = tuple(
        PrescribedExercise.from_dict(item)
        for item in exercises_raw
        if isinstance(item, dict)
    )
    nutrition = json.loads(row["nutrition_override_json"] or "{}")
    return PlanDay(
        id=row["id"],
        cycle_id=row["cycle_id"],
        user_id=row["user_id"],
        week_index=int(row["week_index"]),
        day_of_week=int(row["day_of_week"]),
        scheduled_date=row["scheduled_date"],
        day_type=row["day_type"],
        focus=row["focus"] or "",
        estimated_duration_min=row["estimated_duration_min"],
        prescribed_exercises=exercises,
        nutrition_override=nutrition if isinstance(nutrition, dict) else {},
        status_override=row["status_override"],
        notes=row["notes"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
