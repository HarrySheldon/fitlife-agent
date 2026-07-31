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
                result = backup_connection.execute("PRAGMA quick_check").fetchone()[0]
                if result != "ok":
                    raise sqlite3.DatabaseError("backup quick_check failed")
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
    )
