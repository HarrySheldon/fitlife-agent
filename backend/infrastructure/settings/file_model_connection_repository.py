from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from uuid import uuid4

from backend.domain.model_connection import ModelConnection, ModelConnectionWorkspace, PublicModelConnection
from backend.infrastructure.user_lifecycle import user_lifecycle_guard


_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class FileModelConnectionRepository:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)

    def get(self, user_id: str) -> ModelConnection | None:
        return self.get_workspace(user_id).active

    def get_workspace(self, user_id: str) -> ModelConnectionWorkspace:
        path = self._path(user_id)
        with _lock_for(path):
            return self._read(path)

    @staticmethod
    def _read(path: Path) -> ModelConnectionWorkspace:
        if not path.exists():
            return ModelConnectionWorkspace()
        return _workspace(json.loads(path.read_text(encoding="utf-8")))

    def project_public(self, snapshot: bytes) -> PublicModelConnection:
        payload = json.loads(snapshot.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Model connection source must contain an object")
        return (_workspace(payload).active or ModelConnection()).to_public()

    def project_workspace(self, snapshot: bytes):
        return _workspace(json.loads(snapshot.decode("utf-8"))).to_public()

    def save(self, user_id: str, connection: ModelConnection) -> None:
        """Internal compatibility writer; public writes must use verified use cases."""
        path = self._path(user_id)
        with user_lifecycle_guard(self.data_dir, user_id):
            with _lock_for(path):
                current = self._read(path)
                self._write(path, current.model_copy(update={"active": connection, "revision": current.revision + 1}))

    def compare_and_set(self, user_id: str, *, expected_revision: int,
                        workspace: ModelConnectionWorkspace) -> ModelConnectionWorkspace:
        from backend.domain.errors import ApplicationError

        path = self._path(user_id)
        with user_lifecycle_guard(self.data_dir, user_id), _lock_for(path):
            current = self._read(path)
            if current.revision != expected_revision:
                raise ApplicationError(code="MODEL_CONFIGURATION_CONFLICT", message="The model configuration changed. Reload before saving.", status_code=409)
            if workspace.revision != current.revision + 1:
                raise ValueError("Workspace revision must increase by one")
            validated = ModelConnectionWorkspace.model_validate(workspace.model_dump())
            self._write(path, validated)
            return validated

    def _write(self, path: Path, workspace: ModelConnectionWorkspace) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        payload = json.dumps(workspace.model_dump(mode="json"), ensure_ascii=False, indent=2)
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
        return self.data_dir / "users" / user_id / "model_connection.json"


def _lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(resolved, threading.Lock())


def _workspace(payload: dict) -> ModelConnectionWorkspace:
    if not isinstance(payload, dict):
        raise ValueError("Model connection source must contain an object")
    if "schema_version" in payload:
        return ModelConnectionWorkspace.model_validate(payload)
    return ModelConnectionWorkspace(active=ModelConnection.model_validate(payload))
