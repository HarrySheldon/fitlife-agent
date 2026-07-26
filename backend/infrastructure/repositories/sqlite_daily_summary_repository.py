from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from backend.application.ports.daily_summary_repository import (
    DailySummary,
    DailyTargetSnapshot,
    MealSummary,
    NutritionSnapshot,
    WorkoutSummary,
)
from backend.infrastructure.repositories.sqlite_daily_log import (
    bind_existing_daily_log_target,
    ensure_daily_log,
    next_local_midnight_utc,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase


class SQLiteDailySummaryRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get_day(
        self,
        user_id: str,
        log_date: str,
        timezone_name: str,
    ) -> DailySummary:
        cutoff = next_local_midnight_utc(log_date, timezone_name)
        with self.database.transaction() as connection:
            bind_existing_daily_log_target(
                connection,
                user_id,
                log_date,
                timezone_name,
            )
            target = _target(connection, user_id, log_date, cutoff)
            meals = _meals(connection, user_id, log_date)
            workouts = _workouts(connection, user_id, log_date)
            planned = _planned_meal_count(connection, user_id, log_date)
        consumed = NutritionSnapshot(
            calories=_sum(meals, "calories"),
            carbs=_sum(meals, "carbs"),
            protein=_sum(meals, "protein"),
            fat=_sum(meals, "fat"),
        )
        return DailySummary(
            date=log_date,
            target=target,
            consumed=consumed,
            planned_meal_count=max(planned, len(meals)),
            recorded_meal_count=len(meals),
            meals=meals,
            workouts=workouts,
        )

    def set_planned_meal_count(
        self,
        user_id: str,
        log_date: str,
        planned_meal_count: int,
        timezone_name: str,
    ) -> DailySummary:
        now = (
            datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
        with self.database.transaction() as connection:
            ensure_daily_log(
                connection,
                lambda: uuid4().hex,
                user_id,
                log_date,
                now,
                timezone_name,
            )
            connection.execute(
                """
                UPDATE daily_logs
                SET planned_meal_count = MAX(
                        ?,
                        (
                            SELECT COUNT(*)
                            FROM meals
                            WHERE user_id = ? AND log_date = ?
                        )
                    ),
                    updated_at = ?
                WHERE user_id = ? AND log_date = ?
                """,
                (
                    planned_meal_count,
                    user_id,
                    log_date,
                    now,
                    user_id,
                    log_date,
                ),
            )
        return self.get_day(user_id, log_date, timezone_name)


def _target(
    connection,
    user_id: str,
    log_date: str,
    cutoff: str,
) -> DailyTargetSnapshot | None:
    row = connection.execute(
        """
        SELECT target.id, target.calories, target.carbs, target.protein,
               target.fat, target.source, target.effective_from
        FROM daily_target_versions AS target
        LEFT JOIN daily_logs AS log
          ON log.user_id = target.user_id
         AND log.log_date = ?
         AND log.target_version_id = target.id
        WHERE target.user_id = ?
          AND (
            log.target_version_id IS NOT NULL
            OR (
              NOT EXISTS (
                SELECT 1 FROM daily_logs
                WHERE user_id = ? AND log_date = ?
                  AND target_version_id IS NOT NULL
              )
              AND julianday(target.effective_from) < julianday(?)
            )
          )
        ORDER BY (log.target_version_id IS NOT NULL) DESC,
                 julianday(target.effective_from) DESC,
                 target.effective_from DESC, target.created_at DESC,
                 target.id DESC
        LIMIT 1
        """,
        (log_date, user_id, user_id, log_date, cutoff),
    ).fetchone()
    if row is None:
        return None
    return DailyTargetSnapshot(
        id=row["id"],
        calories=_number(row["calories"]),
        carbs=_number(row["carbs"]),
        protein=_number(row["protein"]),
        fat=_number(row["fat"]),
        source=row["source"],
        effective_from=row["effective_from"],
    )


def _planned_meal_count(connection, user_id: str, log_date: str) -> int:
    row = connection.execute(
        """
        SELECT planned_meal_count
        FROM daily_logs
        WHERE user_id = ? AND log_date = ?
        """,
        (user_id, log_date),
    ).fetchone()
    return int(row["planned_meal_count"]) if row is not None else 3


def _meals(connection, user_id: str, log_date: str) -> tuple[MealSummary, ...]:
    rows = connection.execute(
        """
        SELECT
            meal.id,
            meal.name,
            meal.meal_type,
            meal.position,
            COUNT(item.id) AS item_count,
            COALESCE(SUM(item.calories), 0) AS calories,
            COALESCE(SUM(item.carbs), 0) AS carbs,
            COALESCE(SUM(item.protein), 0) AS protein,
            COALESCE(SUM(item.fat), 0) AS fat
        FROM meals AS meal
        JOIN meal_items AS item ON item.meal_id = meal.id
        WHERE meal.user_id = ? AND meal.log_date = ?
        GROUP BY meal.id
        ORDER BY meal.position, meal.created_at, meal.id
        """,
        (user_id, log_date),
    ).fetchall()
    return tuple(
        MealSummary(
            id=row["id"],
            name=row["name"],
            meal_type=row["meal_type"],
            position=int(row["position"]),
            item_count=int(row["item_count"]),
            nutrition=NutritionSnapshot(
                calories=_number(row["calories"]),
                carbs=_number(row["carbs"]),
                protein=_number(row["protein"]),
                fat=_number(row["fat"]),
            ),
        )
        for row in rows
    )


def _workouts(
    connection,
    user_id: str,
    log_date: str,
) -> tuple[WorkoutSummary, ...]:
    rows = connection.execute(
        """
        SELECT
            session.id,
            session.title,
            session.started_at,
            session.duration_min,
            session.intensity,
            session.estimated_calories,
            session.estimate_json,
            COUNT(DISTINCT strength.id) AS strength_exercise_count,
            COUNT(DISTINCT strength_set.id) AS strength_set_count,
            COUNT(DISTINCT cardio.id) AS cardio_item_count
        FROM training_sessions AS session
        LEFT JOIN strength_exercises AS strength
          ON strength.session_id = session.id
        LEFT JOIN strength_sets AS strength_set
          ON strength_set.strength_exercise_id = strength.id
        LEFT JOIN cardio_items AS cardio
          ON cardio.session_id = session.id
        WHERE session.user_id = ? AND session.log_date = ?
        GROUP BY session.id
        ORDER BY COALESCE(session.started_at, session.created_at),
                 session.created_at, session.id
        """,
        (user_id, log_date),
    ).fetchall()
    return tuple(
        WorkoutSummary(
            id=row["id"],
            title=row["title"],
            started_at=row["started_at"],
            duration_min=_optional_number(row["duration_min"]),
            intensity=row["intensity"],
            calories=_optional_number(
                row["estimated_calories"]
            ),
            contains_estimates=bool(
                json.loads(row["estimate_json"]).get("contains_estimates")
            ),
            strength_exercise_count=int(row["strength_exercise_count"]),
            strength_set_count=int(row["strength_set_count"]),
            cardio_item_count=int(row["cardio_item_count"]),
        )
        for row in rows
    )


def _sum(meals: tuple[MealSummary, ...], field: str) -> float:
    return _number(
        sum(getattr(meal.nutrition, field) for meal in meals)
    )


def _number(value: float) -> float:
    return round(float(value), 2)


def _optional_number(value: float | None) -> float | None:
    return _number(value) if value is not None else None
