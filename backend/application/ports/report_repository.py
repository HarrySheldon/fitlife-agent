from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict
from backend.schemas import WeeklyReport


class StoredWeeklyReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    week: str
    generated_at: AwareDatetime
    report: WeeklyReport


class ReportRepository(Protocol):
    def save(self, user_id: str, report: StoredWeeklyReport) -> None: ...

    def list(self, user_id: str) -> list[StoredWeeklyReport]: ...

    def get(self, user_id: str, week: str) -> StoredWeeklyReport | None: ...
