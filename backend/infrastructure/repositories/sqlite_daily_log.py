from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def effective_target_id(
    connection,
    user_id: str,
    log_date: str,
    timezone_name: str,
) -> str | None:
    cutoff = next_local_midnight_utc(log_date, timezone_name)
    row = connection.execute(
        """
        SELECT id
        FROM daily_target_versions
        WHERE user_id = ? AND julianday(effective_from) < julianday(?)
        ORDER BY julianday(effective_from) DESC, effective_from DESC,
                 created_at DESC, id DESC
        LIMIT 1
        """,
        (user_id, cutoff),
    ).fetchone()
    return row["id"] if row is not None else None


def ensure_daily_log(
    connection,
    id_factory,
    user_id: str,
    log_date: str,
    now: str,
    timezone_name: str,
) -> None:
    target_id = effective_target_id(
        connection,
        user_id,
        log_date,
        timezone_name,
    )
    connection.execute(
        """
        INSERT INTO daily_logs (
            id, user_id, log_date, planned_meal_count, target_version_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, 3, ?, ?, ?)
        ON CONFLICT(user_id, log_date) DO UPDATE SET
            target_version_id = COALESCE(
                daily_logs.target_version_id,
                excluded.target_version_id
            )
        """,
        (id_factory(), user_id, log_date, target_id, now, now),
    )


def bind_existing_daily_log_target(
    connection,
    user_id: str,
    log_date: str,
    timezone_name: str,
) -> None:
    target_id = effective_target_id(
        connection,
        user_id,
        log_date,
        timezone_name,
    )
    if target_id is None:
        return
    connection.execute(
        """
        UPDATE daily_logs
        SET target_version_id = ?
        WHERE user_id = ? AND log_date = ? AND target_version_id IS NULL
        """,
        (target_id, user_id, log_date),
    )


def next_local_midnight_utc(log_date: str, timezone_name: str) -> str:
    selected = date.fromisoformat(log_date)
    next_day = selected + timedelta(days=1)
    local_midnight = datetime.combine(
        next_day,
        time.min,
        tzinfo=ZoneInfo(timezone_name),
    )
    return (
        local_midnight.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
