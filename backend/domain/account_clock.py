from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def local_today(timezone_name: str, *, now: datetime | None = None) -> date:
    instant = now or utc_now()
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(ZoneInfo(timezone_name)).date()


def local_week_bounds(
    timezone_name: str,
    *,
    now: datetime | None = None,
    selected: date | None = None,
) -> tuple[date, date]:
    current = selected or local_today(timezone_name, now=now)
    start = current - timedelta(days=current.weekday())
    return start, start + timedelta(days=6)

