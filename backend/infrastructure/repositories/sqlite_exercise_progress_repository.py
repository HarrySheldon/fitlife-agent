"""SQLite read repository for strength exercise progression metrics."""
from __future__ import annotations

from datetime import date, timedelta

from backend.domain.exercise_progress import (
    ExerciseProgressSummary,
    StrengthSetRow,
    aggregate_exercise_progress,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase


class SQLiteExerciseProgressRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def list_progress(
        self,
        user_id: str,
        *,
        days: int | None = 90,
        end_date: str | None = None,
    ) -> tuple[ExerciseProgressSummary, ...]:
        params: list[object] = [user_id]
        where_clauses = ["ts.user_id = ?"]
        if days is not None and days > 0:
            anchor = date.fromisoformat(end_date) if end_date else date.today()
            start = (anchor - timedelta(days=days - 1)).isoformat()
            where_clauses.append("ts.log_date >= ?")
            params.append(start)
        if end_date is not None:
            where_clauses.append("ts.log_date <= ?")
            params.append(end_date)

        sql = f"""
            SELECT
                ts.log_date,
                ts.id AS session_id,
                se.catalog_exercise_id,
                se.exercise_name,
                se.primary_muscle,
                ss.reps,
                ss.load_kg,
                ss.bodyweight
            FROM training_sessions AS ts
            INNER JOIN strength_exercises AS se ON se.session_id = ts.id
            INNER JOIN strength_sets AS ss ON ss.strength_exercise_id = se.id
            WHERE {' AND '.join(where_clauses)}
            ORDER BY ts.log_date ASC, ts.created_at ASC, se.position ASC, ss.set_number ASC
        """
        with self.database.connection() as connection:
            rows = connection.execute(sql, params).fetchall()

        set_rows = [
            StrengthSetRow(
                log_date=row["log_date"],
                session_id=row["session_id"],
                catalog_exercise_id=row["catalog_exercise_id"],
                exercise_name=row["exercise_name"],
                primary_muscle=row["primary_muscle"],
                reps=int(row["reps"]),
                load_kg=float(row["load_kg"]) if row["load_kg"] is not None else None,
                bodyweight=bool(row["bodyweight"]),
            )
            for row in rows
        ]
        return aggregate_exercise_progress(set_rows)
