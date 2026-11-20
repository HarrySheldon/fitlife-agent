"""SQLite repository for user body measurements time-series."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from backend.domain.body_measurements import BodyMeasurement
from backend.infrastructure.sqlite.database import SQLiteDatabase


class SQLiteBodyMeasurementRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def create(
        self,
        user_id: str,
        *,
        measured_date: str,
        weight_kg: float | None = None,
        body_fat_pct: float | None = None,
        waist_cm: float | None = None,
        chest_cm: float | None = None,
        hip_cm: float | None = None,
        note: str = "",
        measured_at: str | None = None,
    ) -> BodyMeasurement:
        now = datetime.now(timezone.utc).isoformat()
        record_id = f"bm-{uuid4().hex}"
        ts = measured_at or now
        cleaned_note = note.strip()[:300]
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO body_measurements (
                    id, user_id, measured_date, measured_at,
                    weight_kg, body_fat_pct, waist_cm, chest_cm, hip_cm,
                    note, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    user_id,
                    measured_date,
                    ts,
                    weight_kg,
                    body_fat_pct,
                    waist_cm,
                    chest_cm,
                    hip_cm,
                    cleaned_note,
                    now,
                    now,
                ),
            )
        return BodyMeasurement(
            id=record_id,
            user_id=user_id,
            measured_date=measured_date,
            measured_at=ts,
            weight_kg=weight_kg,
            body_fat_pct=body_fat_pct,
            waist_cm=waist_cm,
            chest_cm=chest_cm,
            hip_cm=hip_cm,
            note=cleaned_note,
            created_at=now,
            updated_at=now,
        )

    def list_for_user(
        self,
        user_id: str,
        *,
        days: int | None = None,
        end_date: str | None = None,
    ) -> tuple[BodyMeasurement, ...]:
        params: list[object] = [user_id]
        where_clauses = ["user_id = ?"]
        if days is not None and days > 0:
            anchor = date.fromisoformat(end_date) if end_date else date.today()
            start = (anchor - timedelta(days=days - 1)).isoformat()
            where_clauses.append("measured_date >= ?")
            params.append(start)
        if end_date is not None:
            where_clauses.append("measured_date <= ?")
            params.append(end_date)

        sql = f"""
            SELECT id, user_id, measured_date, measured_at,
                   weight_kg, body_fat_pct, waist_cm, chest_cm, hip_cm,
                   note, created_at, updated_at
            FROM body_measurements
            WHERE {' AND '.join(where_clauses)}
            ORDER BY measured_date DESC, measured_at DESC, id DESC
        """
        with self.database.connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return tuple(_row_to_measurement(row) for row in rows)

    def latest_for_user(self, user_id: str) -> BodyMeasurement | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, measured_date, measured_at,
                       weight_kg, body_fat_pct, waist_cm, chest_cm, hip_cm,
                       note, created_at, updated_at
                FROM body_measurements
                WHERE user_id = ?
                ORDER BY measured_date DESC, measured_at DESC, id DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        return _row_to_measurement(row) if row is not None else None

    def delete(self, user_id: str, measurement_id: str) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM body_measurements WHERE user_id = ? AND id = ?",
                (user_id, measurement_id),
            )
        return cursor.rowcount > 0


def _row_to_measurement(row) -> BodyMeasurement:
    return BodyMeasurement(
        id=row["id"],
        user_id=row["user_id"],
        measured_date=row["measured_date"],
        measured_at=row["measured_at"],
        weight_kg=row["weight_kg"],
        body_fat_pct=row["body_fat_pct"],
        waist_cm=row["waist_cm"],
        chest_cm=row["chest_cm"],
        hip_cm=row["hip_cm"],
        note=row["note"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
