from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from backend.infrastructure.sqlite.database import SQLiteDatabase


@dataclass(frozen=True)
class DatabaseBackup:
    path: Path
    checksum: str
    bytes: int
    integrity_check: str = "ok"
    schema_version: int | None = None
    user_count: int = 0
    model_connection_count: int = 0


def backup_database(
    database: SQLiteDatabase,
    destination: Path,
) -> DatabaseBackup:
    target = Path(destination).resolve(strict=False)
    source = database.path.resolve(strict=False)
    if target == source:
        raise ValueError("Backup destination must differ from the live database")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        with database.connection() as source_connection:
            backup_connection = sqlite3.connect(temporary)
            try:
                source_connection.backup(backup_connection)
                integrity, schema_version, user_count, model_count = _inspect_sqlite_connection(
                    backup_connection
                )
            finally:
                backup_connection.close()
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    content = target.read_bytes()
    return DatabaseBackup(
        path=target,
        checksum=hashlib.sha256(content).hexdigest(),
        bytes=len(content),
        integrity_check=integrity,
        schema_version=schema_version,
        user_count=user_count,
        model_connection_count=model_count,
    )


def verify_database_backup(backup_path: Path) -> DatabaseBackup:
    target = Path(backup_path).resolve(strict=True)
    if not target.is_file():
        raise FileNotFoundError(f"Backup file does not exist: {target}")
    connection = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
    try:
        integrity, schema_version, user_count, model_count = _inspect_sqlite_connection(
            connection
        )
    finally:
        connection.close()
    content = target.read_bytes()
    return DatabaseBackup(
        path=target,
        checksum=hashlib.sha256(content).hexdigest(),
        bytes=len(content),
        integrity_check=integrity,
        schema_version=schema_version,
        user_count=user_count,
        model_connection_count=model_count,
    )


def restore_database_backup(backup_path: Path, destination: Path) -> DatabaseBackup:
    verified = verify_database_backup(backup_path)
    target = Path(destination).resolve(strict=False)
    if target == verified.path:
        raise ValueError("Restore destination must differ from the backup source")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        source_connection = sqlite3.connect(
            f"file:{verified.path.as_posix()}?mode=ro", uri=True
        )
        try:
            restore_connection = sqlite3.connect(temporary)
            try:
                source_connection.backup(restore_connection)
                integrity, schema_version, user_count, model_count = _inspect_sqlite_connection(
                    restore_connection
                )
            finally:
                restore_connection.close()
        finally:
            source_connection.close()
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    content = target.read_bytes()
    return DatabaseBackup(
        path=target,
        checksum=hashlib.sha256(content).hexdigest(),
        bytes=len(content),
        integrity_check=integrity,
        schema_version=schema_version,
        user_count=user_count,
        model_connection_count=model_count,
    )


def _inspect_sqlite_connection(
    connection: sqlite3.Connection,
) -> tuple[str, int | None, int, int]:
    row = connection.execute("PRAGMA integrity_check").fetchone()
    integrity = str(row[0]) if row is not None else "failed"
    if integrity != "ok":
        raise sqlite3.DatabaseError(f"SQLite integrity check failed: {integrity}")

    schema_version: int | None = None
    if _table_exists(connection, "schema_migrations"):
        version_row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        if version_row is not None and version_row[0] is not None:
            schema_version = int(version_row[0])

    user_count = 0
    if _table_exists(connection, "users"):
        user_count = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    model_connection_count = 0
    if _table_exists(connection, "model_connections"):
        model_connection_count = int(
            connection.execute("SELECT COUNT(*) FROM model_connections").fetchone()[0]
        )

    return integrity, schema_version, user_count, model_connection_count


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )
