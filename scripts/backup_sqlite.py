from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import get_settings


_ENCRYPTION_KEY_NOTICE = (
    "Model API keys stored in model_connections remain Fernet-encrypted. "
    "Back up SETTINGS_ENCRYPTION_KEY separately in a safe offline location."
)


@dataclass(frozen=True)
class SQLiteBackupResult:
    path: Path
    checksum: str
    bytes: int
    integrity_check: str
    schema_version: int | None
    user_count: int
    model_connection_count: int


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_count(conn: sqlite3.Connection, table_name: str) -> int:
    if not _table_exists(conn, table_name):
        return 0
    row = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
    return int(row[0]) if row is not None else 0


def verify_sqlite_backup(path: Path) -> SQLiteBackupResult:
    target = Path(path).resolve(strict=True)
    if not target.is_file():
        raise FileNotFoundError(f"SQLite file does not exist: {target}")
    conn = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
    try:
        integrity_row = conn.execute("PRAGMA integrity_check").fetchone()
        integrity = str(integrity_row[0]) if integrity_row else "failed"
        if integrity != "ok":
            raise sqlite3.DatabaseError(f"SQLite integrity_check failed for {target}: {integrity}")
        schema_version: int | None = None
        if _table_exists(conn, "schema_migrations"):
            row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            if row is not None and row[0] is not None:
                schema_version = int(row[0])
        user_count = _table_count(conn, "users")
        model_connection_count = _table_count(conn, "model_connections")
    finally:
        conn.close()

    content = target.read_bytes()
    return SQLiteBackupResult(
        path=target,
        checksum=hashlib.sha256(content).hexdigest(),
        bytes=len(content),
        integrity_check=integrity,
        schema_version=schema_version,
        user_count=user_count,
        model_connection_count=model_connection_count,
    )


def backup_sqlite_file(source: Path, destination: Path) -> SQLiteBackupResult:
    src_path = Path(source).resolve(strict=True)
    dst_path = Path(destination).resolve(strict=False)
    if src_path == dst_path:
        raise ValueError("Refusing to write SQLite backup over the live source file")
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = dst_path.with_name(f".{dst_path.name}.{uuid4().hex}.tmp")

    src_conn = sqlite3.connect(f"file:{src_path.as_posix()}?mode=ro", uri=True)
    try:
        dst_conn = sqlite3.connect(temporary)
        try:
            src_conn.backup(dst_conn)
            dst_conn.commit()
        finally:
            dst_conn.close()
    finally:
        src_conn.close()

    try:
        os.replace(temporary, dst_path)
    finally:
        if temporary.exists():
            temporary.unlink()

    return verify_sqlite_backup(dst_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or verify a FitLife SQLite backup")
    parser.add_argument("--database", type=Path, default=None, help="Source SQLite file path.")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--manifest",
        action="store_true",
        help="Write a companion <output>.manifest.json file next to the backup.",
    )
    parser.add_argument(
        "--verify-only",
        type=Path,
        default=None,
        help="Verify an existing SQLite backup file without creating a new copy.",
    )
    args = parser.parse_args()

    if args.verify_only is not None:
        result = verify_sqlite_backup(args.verify_only)
    else:
        source = args.database or (get_settings().data_dir / "fitlife.sqlite3")
        output = args.output or (
            Path("backups")
            / f"fitlife-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
        )
        result = backup_sqlite_file(source, output)

    summary: dict[str, object] = {
        "path": str(result.path),
        "sha256": result.checksum,
        "bytes": result.bytes,
        "integrity_check": result.integrity_check,
        "schema_version": result.schema_version,
        "user_count": result.user_count,
        "model_connection_count": result.model_connection_count,
        "encryption_key_notice": _ENCRYPTION_KEY_NOTICE,
    }

    if args.manifest:
        manifest_path = Path(f"{result.path}.manifest.json")
        manifest_payload = {
            **summary,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest_path.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        summary["manifest_path"] = str(manifest_path)

    print(json.dumps(summary, separators=(",", ":")))


if __name__ == "__main__":
    main()
