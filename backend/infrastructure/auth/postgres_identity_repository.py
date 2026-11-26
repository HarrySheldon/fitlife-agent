from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, RLock
from uuid import uuid4

from backend.application.ports.identity_repository import (
    AccountDeletionStatus,
    IdentityExportMetadata,
    PasswordChangeResult,
)
from backend.infrastructure.auth.file_identity_repository import (
    FileIdentityRepository,
    hash_password,
    normalize_email,
    normalize_phone,
    normalize_username,
    verify_password,
)
from backend.infrastructure.migration.legacy_account_state import LegacyAccountStateMigrator
from backend.infrastructure.postgres.database import PostgresDatabase
from backend.infrastructure.postgres.runtime import ensure_database_ready
from backend.schemas import AuthenticatedUser

_ACCOUNT_LOCKS: dict[tuple[str, str], RLock] = {}
_ACCOUNT_LOCKS_GUARD = Lock()


def _account_lock_for(database: PostgresDatabase) -> RLock:
    key = (database.dsn, database.target_schema)
    with _ACCOUNT_LOCKS_GUARD:
        lock = _ACCOUNT_LOCKS.get(key)
        if lock is None:
            lock = RLock()
            _ACCOUNT_LOCKS[key] = lock
        return lock


class PostgresIdentityRepository:
    def __init__(self, database: PostgresDatabase, data_dir: Path | None = None) -> None:
        self.database = database
        self.data_dir = Path(data_dir) if data_dir is not None else None

    def _prepare(self) -> None:
        ensure_database_ready(self.database)
        if self.data_dir is not None and (self.data_dir / "users.json").is_file():
            LegacyAccountStateMigrator(self.database, self.data_dir).migrate()

    def register(
        self,
        username: str | None,
        email: str | None,
        phone: str | None,
        password: str,
        display_name: str,
    ) -> AuthenticatedUser:
        self._prepare()
        normalized_username = normalize_username(username) or None if username else None
        normalized_email = normalize_email(email) or None if email else None
        normalized_phone = normalize_phone(phone) or None if phone else None
        user_id = uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        password_hash = hash_password(password)
        clean_display_name = display_name.strip()

        with self.database.transaction() as connection:
            for column, value, label in (
                ("username", normalized_username, "Username"),
                ("email", normalized_email, "Email"),
                ("phone", normalized_phone, "Phone"),
            ):
                if value is not None:
                    exists = connection.execute(
                        f"SELECT 1 FROM users WHERE {column} = ?",
                        (value,),
                    ).fetchone()
                    if exists is not None:
                        raise ValueError(f"{label} already registered")

            connection.execute(
                """
                INSERT INTO users (
                    user_id, username, email, phone, display_name,
                    password_hash, token_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    user_id,
                    normalized_username,
                    normalized_email,
                    normalized_phone,
                    clean_display_name,
                    password_hash,
                    created_at,
                ),
            )

        return AuthenticatedUser(
            user_id=user_id,
            username=normalized_username,
            email=normalized_email,
            phone=normalized_phone,
            display_name=clean_display_name,
        )

    def authenticate(self, identifier: str, password: str) -> AuthenticatedUser | None:
        self._prepare()
        normalized_email = normalize_email(identifier)
        normalized_username = normalize_username(identifier)
        normalized_phone = normalize_phone(identifier)

        clauses: list[str] = []
        params: list[str] = []
        if normalized_email:
            clauses.append("email = ?")
            params.append(normalized_email)
        if normalized_username:
            clauses.append("username = ?")
            params.append(normalized_username)
        if normalized_phone:
            clauses.append("phone = ?")
            params.append(normalized_phone)
        if not clauses:
            return None

        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM users WHERE {' OR '.join(clauses)}",
                tuple(params),
            ).fetchall()

        for row in rows:
            if verify_password(password, row["password_hash"]):
                return _public_user(row)
        return None

    def get_by_id(self, user_id: str) -> AuthenticatedUser | None:
        self._prepare()
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return _public_user(row) if row is not None else None

    def has_users(self) -> bool:
        self._prepare()
        with self.database.connection() as connection:
            row = connection.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        return row is not None

    def list_user_ids(self) -> tuple[str, ...]:
        self._prepare()
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT user_id FROM users ORDER BY created_at, user_id"
            ).fetchall()
        return tuple(row["user_id"] for row in rows)

    def export_metadata(self, user_id: str) -> IdentityExportMetadata | None:
        self._prepare()
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT user_id, username, email, phone, display_name, created_at
                FROM users WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return IdentityExportMetadata(
            user_id=row["user_id"],
            username=row["username"],
            email=row["email"],
            phone=row["phone"],
            display_name=row["display_name"],
            created_at=row["created_at"],
        )

    def project_export_metadata(
        self,
        user_id: str,
        snapshot: bytes,
    ) -> IdentityExportMetadata | None:
        return FileIdentityRepository(self.data_dir or Path(".")).project_export_metadata(
            user_id, snapshot
        )

    def verify_user_password(self, user_id: str, password: str) -> bool:
        self._prepare()
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT password_hash FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return bool(row is not None and verify_password(password, row["password_hash"]))

    def replace_password(self, user_id: str, password: str) -> bool:
        self._prepare()
        password_hash = hash_password(password)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE users SET password_hash = ? WHERE user_id = ?",
                (password_hash, user_id),
            )
            return cursor.rowcount > 0

    def change_password_and_rotate_version(
        self,
        user_id: str,
        expected_token_version: int,
        current_password: str,
        new_password: str,
    ) -> PasswordChangeResult:
        self._prepare()
        new_hash = hash_password(new_password) if current_password != new_password else None
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT password_hash, token_version FROM users WHERE user_id = ? FOR UPDATE",
                (user_id,),
            ).fetchone()
            if row is None or int(row["token_version"]) != expected_token_version:
                return PasswordChangeResult(status="token_invalid")
            if not verify_password(current_password, row["password_hash"]):
                return PasswordChangeResult(status="current_password_invalid")
            if current_password == new_password:
                return PasswordChangeResult(status="password_unchanged")
            assert new_hash is not None
            token_version = expected_token_version + 1
            connection.execute(
                "UPDATE users SET password_hash = ?, token_version = ? WHERE user_id = ?",
                (new_hash, token_version, user_id),
            )
        return PasswordChangeResult(status="changed", token_version=token_version)

    def get_token_version(self, user_id: str) -> int | None:
        self._prepare()
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT token_version FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return int(row["token_version"]) if row is not None else None

    def rotate_token_version(
        self,
        user_id: str,
        expected_token_version: int | None = None,
    ) -> int | None:
        self._prepare()
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT token_version FROM users WHERE user_id = ? FOR UPDATE",
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            current_version = int(row["token_version"])
            if expected_token_version is not None and current_version != expected_token_version:
                return None
            token_version = current_version + 1
            connection.execute(
                "UPDATE users SET token_version = ? WHERE user_id = ?",
                (token_version, user_id),
            )
        return token_version

    def validate_token_version(self, user_id: str, token_version: int) -> AuthenticatedUser | None:
        self._prepare()
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None or int(row["token_version"]) != token_version:
            return None
        return _public_user(row)

    def delete_identity(self, user_id: str) -> bool:
        self._prepare()
        return self._delete_user_row(user_id)

    def confirm_and_delete_account(
        self,
        user_id: str,
        expected_token_version: int,
        password: str,
        cleanup: Callable[[], None],
    ) -> AccountDeletionStatus:
        self._prepare()
        with _account_lock_for(self.database):
            with self.database.connection() as connection:
                row = connection.execute(
                    "SELECT password_hash, token_version FROM users WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
            if row is None or int(row["token_version"]) != expected_token_version:
                return "token_invalid"
            if not verify_password(password, row["password_hash"]):
                return "current_password_invalid"
            cleanup()
            self._delete_user_row(user_id)
        return "deleted"

    def _delete_user_row(self, user_id: str) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM users WHERE user_id = ?",
                (user_id,),
            )
            return cursor.rowcount > 0


def _public_user(row) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=row["user_id"],
        username=row["username"],
        email=row["email"],
        phone=row["phone"],
        display_name=row["display_name"],
    )
