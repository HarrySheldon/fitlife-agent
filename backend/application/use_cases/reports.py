from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from backend.application.ports.report_repository import ReportRepository, StoredWeeklyReport
from backend.domain.errors import ApplicationError


_ISO_WEEK_PATTERN = re.compile(r"^(\d{4})-W(\d{2})$")


class WeeklyReports:
    def __init__(
        self,
        repository: ReportRepository,
        generate_report: Callable[[str, date, date], dict],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.generate_report = generate_report
        self.now = now or (lambda: datetime.now(timezone.utc))

    def list(self, user_id: str) -> list[StoredWeeklyReport]:
        return self.repository.list(user_id)

    def get(self, user_id: str, week: str) -> StoredWeeklyReport:
        iso_week_bounds(week)
        report = self.repository.get(user_id, week)
        if report is None:
            raise ApplicationError(
                code="REPORT_NOT_FOUND",
                message="The requested weekly report does not exist.",
                status_code=404,
                processing_mode="deterministic",
            )
        return report

    def generate(self, user_id: str, week: str) -> StoredWeeklyReport:
        start, end = iso_week_bounds(week)
        report = StoredWeeklyReport(
            week=week,
            generated_at=self.now(),
            report=self.generate_report(user_id, start, end),
        )
        self.repository.save(user_id, report)
        return report


def iso_week_bounds(week: str) -> tuple[date, date]:
    match = _ISO_WEEK_PATTERN.fullmatch(week)
    if match is None:
        raise _invalid_week_error()
    try:
        start = date.fromisocalendar(int(match.group(1)), int(match.group(2)), 1)
    except ValueError as error:
        raise _invalid_week_error() from error
    return start, start + timedelta(days=6)


def _invalid_week_error() -> ApplicationError:
    return ApplicationError(
        code="REPORT_WEEK_INVALID",
        message="Use a valid ISO week key in YYYY-Www format.",
        status_code=422,
        processing_mode="deterministic",
    )
