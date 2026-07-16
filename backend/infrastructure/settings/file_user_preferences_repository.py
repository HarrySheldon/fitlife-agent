from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from uuid import uuid4

from backend.domain.user_preferences import UserPreferences
from backend.infrastructure.user_lifecycle import user_lifecycle_guard


_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class FileUserPreferencesRepository:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)

    def get(self, user_id: str) -> UserPreferences | None:
        path = self._path(user_id)
        if not path.exists():
            return None
        with _lock_for(path):
            payload = json.loads(path.read_text(encoding="utf-8"))
        return UserPreferences.model_validate(payload)

    def save(self, user_id: str, preferences: UserPreferences) -> None:
        path = self._path(user_id)
        with user_lifecycle_guard(self.data_dir, user_id):
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
            payload = json.dumps(preferences.model_dump(mode="json"), ensure_ascii=False, indent=2)
            with _lock_for(path):
                try:
                    temporary.write_text(payload, encoding="utf-8")
                    self.replace_file(temporary, path)
                finally:
                    if temporary.exists():
                        temporary.unlink()

    def replace_file(self, source: Path, destination: Path) -> None:
        os.replace(source, destination)

    def _path(self, user_id: str) -> Path:
        if not _USER_ID_PATTERN.fullmatch(user_id):
            raise ValueError("Invalid user id")
        return self.data_dir / "users" / user_id / "preferences.json"


def _lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(resolved, threading.Lock())
