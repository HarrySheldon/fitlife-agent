from __future__ import annotations

import json
import re
from contextlib import nullcontext
from pathlib import Path

from backend.domain.model_connection import (
    ModelConnection,
    ModelConnectionWorkspace,
    PublicModelConnection,
    utc_now_iso,
)
from backend.infrastructure.postgres.database import PostgresDatabase
from backend.infrastructure.postgres.runtime import ensure_database_ready
from backend.infrastructure.settings.file_model_connection_repository import (
    FileModelConnectionRepository,
    _workspace,
)
from backend.infrastructure.user_lifecycle import user_lifecycle_guard

_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class PostgresModelConnectionRepository:
    def __init__(self, database: PostgresDatabase, data_dir: Path | None = None) -> None:
        self.database = database
        self.data_dir = Path(data_dir) if data_dir is not None else None

    def get(self, user_id: str) -> ModelConnection | None:
        return self.get_workspace(user_id).active

    def has_stored_workspace(self, user_id: str) -> bool:
        if not _USER_ID_PATTERN.fullmatch(user_id):
            raise ValueError("Invalid user id")
        ensure_database_ready(self.database)
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM model_connections WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is not None:
            return True
        return bool(self.data_dir is not None and self._legacy_path(user_id).is_file())

    def get_workspace(self, user_id: str) -> ModelConnectionWorkspace:
        if not _USER_ID_PATTERN.fullmatch(user_id):
            raise ValueError("Invalid user id")
        ensure_database_ready(self.database)
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT schema_version, revision, active_json, draft_json
                FROM model_connections
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is not None:
            return _workspace_from_row(row)
        if self.data_dir is not None and self._legacy_path(user_id).is_file():
            return FileModelConnectionRepository(self.data_dir).get_workspace(user_id)
        return ModelConnectionWorkspace()

    def project_public(self, snapshot: bytes) -> PublicModelConnection:
        payload = json.loads(snapshot.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Model connection source must contain an object")
        return (_workspace(payload).active or ModelConnection()).to_public()

    def project_workspace(self, snapshot: bytes):
        return _workspace(json.loads(snapshot.decode("utf-8"))).to_public()

    def save(self, user_id: str, connection: ModelConnection) -> None:
        """Internal compatibility writer; public writes must use verified use cases."""
        if not _USER_ID_PATTERN.fullmatch(user_id):
            raise ValueError("Invalid user id")
        ensure_database_ready(self.database)
        guard = (
            user_lifecycle_guard(self.data_dir, user_id)
            if self.data_dir is not None
            else nullcontext()
        )
        with guard, self.database.transaction() as db_conn:
            current = self._read_unlocked(db_conn, user_id, for_update=True)
            updated = current.model_copy(
                update={"active": connection, "revision": current.revision + 1}
            )
            self._write_unlocked(db_conn, user_id, updated)

    def compare_and_set(
        self,
        user_id: str,
        *,
        expected_revision: int,
        workspace: ModelConnectionWorkspace,
    ) -> ModelConnectionWorkspace:
        from backend.domain.errors import ApplicationError

        if not _USER_ID_PATTERN.fullmatch(user_id):
            raise ValueError("Invalid user id")
        ensure_database_ready(self.database)
        guard = (
            user_lifecycle_guard(self.data_dir, user_id)
            if self.data_dir is not None
            else nullcontext()
        )
        with guard, self.database.transaction() as db_conn:
            current = self._read_unlocked(db_conn, user_id, for_update=True)
            if current.revision != expected_revision:
                raise ApplicationError(
                    code="MODEL_CONFIGURATION_CONFLICT",
                    message="The model configuration changed. Reload before saving.",
                    status_code=409,
                )
            if workspace.revision != current.revision + 1:
                raise ValueError("Workspace revision must increase by one")
            validated = ModelConnectionWorkspace.model_validate(workspace.model_dump())
            self._write_unlocked(db_conn, user_id, validated)
            return validated

    def delete_user_data(self, user_id: str) -> None:
        ensure_database_ready(self.database)
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM model_connections WHERE user_id = ?",
                (user_id,),
            )

    def _read_unlocked(
        self,
        db_conn,
        user_id: str,
        *,
        for_update: bool = False,
    ) -> ModelConnectionWorkspace:
        suffix = " FOR UPDATE" if for_update else ""
        row = db_conn.execute(
            f"""
            SELECT schema_version, revision, active_json, draft_json
            FROM model_connections
            WHERE user_id = ?{suffix}
            """,
            (user_id,),
        ).fetchone()
        if row is not None:
            return _workspace_from_row(row)
        if self.data_dir is not None and self._legacy_path(user_id).is_file():
            return FileModelConnectionRepository(self.data_dir).get_workspace(user_id)
        return ModelConnectionWorkspace()

    def _write_unlocked(self, db_conn, user_id: str, workspace: ModelConnectionWorkspace) -> None:
        active_json = (
            json.dumps(workspace.active.model_dump(mode="json"), ensure_ascii=False)
            if workspace.active is not None
            else None
        )
        draft_json = (
            json.dumps(workspace.draft.model_dump(mode="json"), ensure_ascii=False)
            if workspace.draft is not None
            else None
        )
        db_conn.execute(
            """
            INSERT INTO model_connections (
                user_id, schema_version, revision, active_json, draft_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                schema_version = excluded.schema_version,
                revision = excluded.revision,
                active_json = excluded.active_json,
                draft_json = excluded.draft_json,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                workspace.schema_version,
                workspace.revision,
                active_json,
                draft_json,
                utc_now_iso(),
            ),
        )

    def _legacy_path(self, user_id: str) -> Path:
        assert self.data_dir is not None
        return self.data_dir / "users" / user_id / "model_connection.json"


def _workspace_from_row(row) -> ModelConnectionWorkspace:
    return ModelConnectionWorkspace(
        schema_version=row["schema_version"],
        revision=row["revision"],
        active=ModelConnection.model_validate_json(row["active_json"]) if row["active_json"] else None,
        draft=ModelConnection.model_validate_json(row["draft_json"]) if row["draft_json"] else None,
    )
