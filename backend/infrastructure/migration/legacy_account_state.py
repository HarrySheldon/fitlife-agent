from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.domain.model_connection import ModelConnectionWorkspace, utc_now_iso
from backend.domain.user_preferences import UserPreferences
from backend.infrastructure.auth.file_identity_repository import (
    normalize_email,
    normalize_phone,
    normalize_username,
)
from backend.infrastructure.settings.file_model_connection_repository import _workspace
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.runtime import ensure_database_ready


MIGRATION_KEY = "legacy_account_state_v1"
_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@dataclass(frozen=True)
class LegacyAccountStateResult:
    status: str
    users_imported: int
    preferences_imported: int
    model_connections_imported: int


class LegacyAccountStateMigrator:
    """Idempotently imports legacy JSON identity, preference, and model files into SQLite.

    Original JSON files remain untouched on disk as a read-only recovery backup.
    """

    def __init__(self, database: SQLiteDatabase, data_dir: Path) -> None:
        self.database = database
        self.data_dir = Path(data_dir)

    def migrate(self) -> LegacyAccountStateResult:
        ensure_database_ready(self.database)
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT status FROM data_migrations WHERE migration_key = ?",
                (MIGRATION_KEY,),
            ).fetchone()
            if existing is not None and existing["status"] == "completed":
                return LegacyAccountStateResult(
                    status="skipped",
                    users_imported=0,
                    preferences_imported=0,
                    model_connections_imported=0,
                )

            users_payload, users_bytes = self._read_legacy_users()
            checksum_parts = [users_bytes]
            users_imported = 0
            preferences_imported = 0
            model_connections_imported = 0
            candidate_ids: set[str] = set()

            for item in users_payload:
                if not isinstance(item, dict):
                    continue
                user_id = item.get("user_id")
                if not isinstance(user_id, str) or not _USER_ID_PATTERN.fullmatch(user_id):
                    continue
                candidate_ids.add(user_id)
                password_hash = item.get("password_hash")
                if not isinstance(password_hash, str) or not password_hash:
                    continue
                username = normalize_username(item.get("username")) or None
                email = normalize_email(item.get("email")) or None if item.get("email") else None
                phone = normalize_phone(item.get("phone")) or None if item.get("phone") else None
                display_name = str(item.get("display_name") or "").strip() or (
                    username or email or phone or user_id
                )
                raw_version = item.get("token_version", 0)
                token_version = raw_version if isinstance(raw_version, int) and raw_version >= 0 else 0
                created_at = str(item.get("created_at") or datetime.now(timezone.utc).isoformat())

                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO users (
                        user_id, username, email, phone, display_name,
                        password_hash, token_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        username,
                        email,
                        phone,
                        display_name,
                        password_hash,
                        token_version,
                        created_at,
                    ),
                )
                if cursor.rowcount > 0:
                    users_imported += 1

            for (existing_id,) in connection.execute("SELECT user_id FROM users").fetchall():
                if isinstance(existing_id, str) and _USER_ID_PATTERN.fullmatch(existing_id):
                    candidate_ids.add(existing_id)

            users_root = self.data_dir / "users"
            if users_root.is_dir() and not users_root.is_symlink():
                for entry in users_root.iterdir():
                    if entry.is_dir() and not entry.is_symlink() and _USER_ID_PATTERN.fullmatch(entry.name):
                        candidate_ids.add(entry.name)

            now_iso = utc_now_iso()
            for user_id in sorted(candidate_ids):
                user_dir = users_root / user_id
                if not user_dir.is_dir() or user_dir.is_symlink():
                    continue

                pref_path = user_dir / "preferences.json"
                pref_data, pref_bytes = _read_json_file(pref_path)
                if pref_data is not None:
                    checksum_parts.append(pref_bytes)
                    try:
                        prefs = UserPreferences.model_validate(pref_data)
                    except ValueError:
                        prefs = None
                    if prefs is not None:
                        cursor = connection.execute(
                            """
                            INSERT OR IGNORE INTO user_preferences (
                                user_id, language, unit_system, timezone, updated_at
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            (user_id, prefs.language, prefs.unit_system, prefs.timezone, now_iso),
                        )
                        if cursor.rowcount > 0:
                            preferences_imported += 1

                model_path = user_dir / "model_connection.json"
                model_data, model_bytes = _read_json_file(model_path)
                if isinstance(model_data, dict):
                    checksum_parts.append(model_bytes)
                    try:
                        workspace: ModelConnectionWorkspace = _workspace(model_data)
                    except ValueError:
                        workspace = None  # type: ignore[assignment]
                    if workspace is not None:
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
                        updated_at = (
                            (workspace.draft.updated_at if workspace.draft is not None else None)
                            or (workspace.active.updated_at if workspace.active is not None else None)
                            or now_iso
                        )
                        cursor = connection.execute(
                            """
                            INSERT OR IGNORE INTO model_connections (
                                user_id, schema_version, revision, active_json, draft_json, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                user_id,
                                workspace.schema_version,
                                workspace.revision,
                                active_json,
                                draft_json,
                                updated_at,
                            ),
                        )
                        if cursor.rowcount > 0:
                            model_connections_imported += 1

            digest = hashlib.sha256(b"\0".join(checksum_parts)).hexdigest()
            details = {
                "users_imported": users_imported,
                "preferences_imported": preferences_imported,
                "model_connections_imported": model_connections_imported,
            }
            connection.execute(
                """
                INSERT INTO data_migrations (
                    migration_key, user_id, checksum, status,
                    source_backup_path, details_json, started_at, completed_at
                ) VALUES (?, NULL, ?, 'completed', NULL, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(migration_key) DO UPDATE SET
                    checksum = excluded.checksum,
                    status = 'completed',
                    details_json = excluded.details_json,
                    completed_at = CURRENT_TIMESTAMP
                """,
                (
                    MIGRATION_KEY,
                    digest,
                    json.dumps(details, sort_keys=True, separators=(",", ":")),
                ),
            )
            return LegacyAccountStateResult(
                status="completed",
                users_imported=users_imported,
                preferences_imported=preferences_imported,
                model_connections_imported=model_connections_imported,
            )

    def _read_legacy_users(self) -> tuple[list[object], bytes]:
        path = self.data_dir / "users.json"
        if not path.is_file() or path.is_symlink():
            return [], b""
        try:
            raw_bytes = path.read_bytes()
            payload = json.loads(raw_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return [], b""
        if not isinstance(payload, list):
            return [], raw_bytes
        return payload, raw_bytes


def _read_json_file(path: Path) -> tuple[object | None, bytes]:
    if not path.is_file() or path.is_symlink():
        return None, b""
    try:
        raw_bytes = path.read_bytes()
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, b""
    return payload, raw_bytes
