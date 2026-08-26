from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from backend.application.ports.plan_repository import StoredPlan, StoredPlanDraft
from backend.domain.errors import ApplicationError
from backend.infrastructure.user_lifecycle import user_lifecycle_guard


_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_PLAN_ID_PATTERN = re.compile(r"^plan-[a-f0-9]{8,64}$")
_DRAFT_ID_PATTERN = re.compile(r"^draft-[a-f0-9]{16,64}$")


class FilePlanRepository:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)

    def save(self, user_id: str, plan: StoredPlan) -> None:
        path = self._path(user_id, plan.plan_id)
        with user_lifecycle_guard(self.data_dir, user_id):
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
            payload = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2)
            with _lock_for(path):
                try:
                    temporary.write_text(payload, encoding="utf-8")
                    os.replace(temporary, path)
                finally:
                    if temporary.exists():
                        temporary.unlink()

    def list(self, user_id: str) -> list[StoredPlan]:
        directory = self._directory(user_id)
        with user_lifecycle_guard(self.data_dir, user_id):
            if not directory.exists():
                return []
            plans = [self._read(path) for path in directory.glob("*.json")]
            return sorted(plans, key=lambda item: item.activated_at, reverse=True)

    def get(self, user_id: str, plan_id: str) -> StoredPlan | None:
        path = self._path(user_id, plan_id)
        with user_lifecycle_guard(self.data_dir, user_id):
            return self._read(path) if path.exists() else None

    def save_draft(self, user_id: str, draft: StoredPlanDraft) -> None:
        path = self._draft_path(user_id, draft.draft_id)
        with user_lifecycle_guard(self.data_dir, user_id):
            path.parent.mkdir(parents=True, exist_ok=True)
            self._write(path, draft.model_dump(mode="json"))

    def get_draft(self, user_id: str, draft_id: str) -> StoredPlanDraft | None:
        path = self._draft_path(user_id, draft_id)
        with user_lifecycle_guard(self.data_dir, user_id):
            return self._read_draft(path) if path.exists() else None

    def take_draft(self, user_id: str, draft_id: str) -> StoredPlanDraft | None:
        path = self._draft_path(user_id, draft_id)
        with user_lifecycle_guard(self.data_dir, user_id):
            try:
                with _lock_for(path):
                    if not path.exists():
                        return None
                    draft = self._read_draft_unlocked(path)
                    path.unlink()
                    return draft
            except (OSError, UnicodeError, json.JSONDecodeError, ValidationError):
                raise self._storage_error() from None

    def _read(self, path: Path) -> StoredPlan:
        try:
            with _lock_for(path):
                payload = json.loads(path.read_text(encoding="utf-8"))
            return StoredPlan.model_validate(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError):
            raise ApplicationError(
                code="PLAN_STORAGE_INVALID",
                message="The saved plan could not be read.",
                status_code=500,
                processing_mode="deterministic",
            ) from None

    def _read_draft(self, path: Path) -> StoredPlanDraft:
        try:
            with _lock_for(path):
                return self._read_draft_unlocked(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError):
            raise self._storage_error() from None

    def _read_draft_unlocked(self, path: Path) -> StoredPlanDraft:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return StoredPlanDraft.model_validate(payload)

    def _write(self, path: Path, payload: dict) -> None:
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        with _lock_for(path):
            try:
                temporary.write_text(encoded, encoding="utf-8")
                os.replace(temporary, path)
            finally:
                if temporary.exists():
                    temporary.unlink()

    @staticmethod
    def _storage_error() -> ApplicationError:
        return ApplicationError(
            code="PLAN_STORAGE_INVALID",
            message="The saved plan could not be read.",
            status_code=500,
            processing_mode="deterministic",
        )

    def _directory(self, user_id: str) -> Path:
        if not _USER_ID_PATTERN.fullmatch(user_id):
            raise ValueError("Invalid user id")
        return self.data_dir / "users" / user_id / "plans"

    def _path(self, user_id: str, plan_id: str) -> Path:
        if not _PLAN_ID_PATTERN.fullmatch(plan_id):
            raise ValueError("Invalid plan id")
        return self._directory(user_id) / f"{plan_id}.json"

    def _draft_path(self, user_id: str, draft_id: str) -> Path:
        if not _DRAFT_ID_PATTERN.fullmatch(draft_id):
            raise ValueError("Invalid draft id")
        return self.data_dir / "users" / self._validated_user_id(user_id) / "plan-drafts" / f"{draft_id}.json"

    def _validated_user_id(self, user_id: str) -> str:
        if not _USER_ID_PATTERN.fullmatch(user_id):
            raise ValueError("Invalid user id")
        return user_id


def _lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(resolved, threading.Lock())
