from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from backend.application.ports.report_repository import StoredWeeklyReport
from backend.domain.errors import ApplicationError
from backend.infrastructure.user_lifecycle import user_lifecycle_guard


_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_WEEK_KEY_PATTERN = re.compile(r"^\d{4}-W\d{2}$")


class FileReportRepository:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)

    def save(self, user_id: str, report: StoredWeeklyReport) -> None:
        path = self._path(user_id, report.week)
        with user_lifecycle_guard(self.data_dir, user_id):
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
            payload = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
            with _lock_for(path):
                try:
                    temporary.write_text(payload, encoding="utf-8")
                    os.replace(temporary, path)
                finally:
                    if temporary.exists():
                        temporary.unlink()

    def list(self, user_id: str) -> list[StoredWeeklyReport]:
        directory = self._directory(user_id)
        with user_lifecycle_guard(self.data_dir, user_id):
            if not directory.exists():
                return []
            reports = [self._read(path) for path in directory.glob("*.json")]
            return sorted(reports, key=lambda item: item.week, reverse=True)

    def get(self, user_id: str, week: str) -> StoredWeeklyReport | None:
        path = self._path(user_id, week)
        with user_lifecycle_guard(self.data_dir, user_id):
            return self._read(path) if path.exists() else None

    def _read(self, path: Path) -> StoredWeeklyReport:
        try:
            with _lock_for(path):
                payload = json.loads(path.read_text(encoding="utf-8"))
            return StoredWeeklyReport.model_validate(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError):
            raise ApplicationError(
                code="REPORT_STORAGE_INVALID",
                message="The saved weekly report could not be read.",
                status_code=500,
                processing_mode="deterministic",
            ) from None

    def _directory(self, user_id: str) -> Path:
        if not _USER_ID_PATTERN.fullmatch(user_id):
            raise ValueError("Invalid user id")
        return self.data_dir / "users" / user_id / "reports"

    def _path(self, user_id: str, week: str) -> Path:
        if not _WEEK_KEY_PATTERN.fullmatch(week):
            raise ValueError("Invalid ISO week key")
        return self._directory(user_id) / f"{week}.json"


def _lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(resolved, threading.Lock())
