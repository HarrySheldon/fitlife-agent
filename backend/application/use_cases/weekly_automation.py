"""Idempotent weekly lazy automation: last week's report + personalized draft plan for review."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import threading

from backend.domain.body_measurements import compute_body_summary
from backend.domain.plan_cycles import (
    GoalType,
    PlanCycle,
    build_personalized_cycle_draft,
    monday_of_week,
)
from backend.infrastructure.repositories.postgres_body_measurement_repository import (
    PostgresBodyMeasurementRepository,
)
from backend.infrastructure.repositories.postgres_exercise_progress_repository import (
    PostgresExerciseProgressRepository,
)
from backend.infrastructure.repositories.postgres_plan_cycle_repository import (
    PostgresPlanCycleRepository,
)
from backend.infrastructure.repositories.postgres_training_context_repository import (
    PostgresTrainingContextRepository,
)
from backend.infrastructure.postgres.database import PostgresDatabase


@dataclass(frozen=True)
class WeeklyAutomationRun:
    user_id: str
    iso_week: str
    report_week: str
    report_status: str
    draft_cycle_id: str | None
    draft_status: str
    message: str
    dismissed: bool
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "iso_week": self.iso_week,
            "report_week": self.report_week,
            "report_status": self.report_status,
            "draft_cycle_id": self.draft_cycle_id,
            "draft_status": self.draft_status,
            "message": self.message,
            "dismissed": self.dismissed,
            "created_at": self.created_at,
        }


def iso_week_id(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def previous_iso_week_id(day: date) -> str:
    return iso_week_id(day - timedelta(days=7))


class WeeklyAutomationService:
    _LOCKS_GUARD = threading.Lock()
    _USER_LOCKS: dict[tuple[str, str], threading.Lock] = {}

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    @classmethod
    def _automation_lock(cls, database: PostgresDatabase, user_id: str) -> threading.Lock:
        key = (f"{database.dsn}|{database.target_schema}", user_id)
        with cls._LOCKS_GUARD:
            lock = cls._USER_LOCKS.get(key)
            if lock is None:
                lock = threading.Lock()
                cls._USER_LOCKS[key] = lock
            return lock

    def get_run(self, user_id: str, iso_week: str) -> WeeklyAutomationRun | None:
        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT user_id, iso_week, report_week, report_status,
                       draft_cycle_id, draft_status, message, dismissed, created_at
                FROM weekly_automation_runs
                WHERE user_id = ? AND iso_week = ?
                """,
                (user_id, iso_week),
            ).fetchone()
        if row is None:
            return None
        return WeeklyAutomationRun(
            user_id=row["user_id"],
            iso_week=row["iso_week"],
            report_week=row["report_week"],
            report_status=row["report_status"],
            draft_cycle_id=row["draft_cycle_id"],
            draft_status=row["draft_status"],
            message=row["message"] or "",
            dismissed=bool(row["dismissed"]),
            created_at=row["created_at"],
        )

    def dismiss(self, user_id: str, iso_week: str) -> bool:
        with self.database.transaction() as conn:
            cursor = conn.execute(
                "UPDATE weekly_automation_runs SET dismissed = 1 WHERE user_id = ? AND iso_week = ?",
                (user_id, iso_week),
            )
        return cursor.rowcount > 0

    def generate_personalized_draft(
        self,
        user_id: str,
        today_date: date,
        *,
        duration_weeks: int = 4,
        goal_type: GoalType = "maintenance",
        target_weight_kg: float | None = None,
        focus_note: str = "",
        source: str = "deterministic",
        title: str | None = None,
    ) -> PlanCycle:
        today_iso = today_date.isoformat()
        cycle_repo = PostgresPlanCycleRepository(self.database)
        ctx = PostgresTrainingContextRepository(self.database).get(user_id)
        progress = PostgresExerciseProgressRepository(self.database).list_progress(
            user_id, days=90, end_date=today_iso
        )
        measurements = PostgresBodyMeasurementRepository(self.database).list_for_user(
            user_id, days=60, end_date=today_iso
        )
        body_summary = compute_body_summary(measurements, target_weight_kg=target_weight_kg)
        prev_adherence = cycle_repo.week_adherence_summary(
            user_id, (today_date - timedelta(days=7)).isoformat()
        )
        catalog = cycle_repo.load_catalog_options(user_id)

        extra_rationale: dict[str, object] = {
            "latest_weight_kg": body_summary.latest_weight_kg,
            "weekly_weight_rate_kg": body_summary.weekly_rate_kg,
            "tracked_exercises_count": len(progress),
        }
        if focus_note.strip():
            extra_rationale["user_focus_note"] = focus_note.strip()[:240]

        week_start = monday_of_week(today_date)
        cycle_payload, days_payload = build_personalized_cycle_draft(
            user_id=user_id,
            goal_type=goal_type,
            start_date=week_start,
            duration_weeks=duration_weeks,
            training_context=ctx,
            catalog=catalog,
            exercise_progress=progress,
            recent_adherence_pct=prev_adherence["pct"] if prev_adherence else None,
            title=title or f"{iso_week_id(today_date)} 个性化训练周期草稿（{duration_weeks}周）",
            source=source,  # type: ignore[arg-type]
            extra_rationale=extra_rationale,
        )
        return cycle_repo.create_draft(user_id, cycle_payload, days_payload)

    def check_and_run(
        self,
        user_id: str,
        today_date: date,
        *,
        goal_type: GoalType = "maintenance",
        target_weight_kg: float | None = None,
        ensure_weekly_report: Callable[[str, str], str] | None = None,
    ) -> WeeklyAutomationRun:
        with self._automation_lock(self.database, user_id):
            return self._check_and_run_locked(
                user_id,
                today_date,
                goal_type=goal_type,
                target_weight_kg=target_weight_kg,
                ensure_weekly_report=ensure_weekly_report,
            )

    def _check_and_run_locked(
        self,
        user_id: str,
        today_date: date,
        *,
        goal_type: GoalType = "maintenance",
        target_weight_kg: float | None = None,
        ensure_weekly_report: Callable[[str, str], str] | None = None,
    ) -> WeeklyAutomationRun:
        current_week = iso_week_id(today_date)
        existing = self.get_run(user_id, current_week)
        if existing is not None:
            return existing

        prev_week = previous_iso_week_id(today_date)
        report_status = "already_exists"
        if ensure_weekly_report is not None:
            try:
                report_status = ensure_weekly_report(user_id, prev_week)
            except Exception:
                report_status = "failed"

        cycle_repo = PostgresPlanCycleRepository(self.database)
        week_start_iso = monday_of_week(today_date).isoformat()
        existing_draft = next(
            (
                c
                for c in cycle_repo.list_cycles(user_id)
                if c.status == "draft" and c.start_date == week_start_iso
            ),
            None,
        )
        draft_cycle_id: str | None = None
        if existing_draft is not None:
            draft_cycle_id = existing_draft.id
            draft_status = "already_exists"
        else:
            try:
                created = self.generate_personalized_draft(
                    user_id,
                    today_date,
                    duration_weeks=4,
                    goal_type=goal_type,
                    target_weight_kg=target_weight_kg,
                    source="weekly_auto_deterministic",
                    title=f"{current_week} 自动生成周计划草稿",
                )
                draft_cycle_id = created.id
                draft_status = "generated_deterministic"
            except Exception:
                draft_status = "failed"

        parts: list[str] = []
        if report_status == "generated":
            parts.append(f"已自动生成上周（{prev_week}）复盘周报")
        if draft_status in {"generated_agent", "generated_deterministic"}:
            parts.append(f"已生成本周（{current_week}）个性化计划草稿，确认后生效")
        message = "；".join(parts) if parts else f"{current_week} 周检查已完成"

        now = datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as conn:
            conn.execute(
                """
                INSERT INTO weekly_automation_runs (
                    user_id, iso_week, report_week, report_status,
                    draft_cycle_id, draft_status, message, dismissed, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT DO NOTHING
                """,
                (
                    user_id,
                    current_week,
                    prev_week,
                    report_status,
                    draft_cycle_id,
                    draft_status,
                    message,
                    now,
                ),
            )
        persisted = self.get_run(user_id, current_week)
        assert persisted is not None
        return persisted
