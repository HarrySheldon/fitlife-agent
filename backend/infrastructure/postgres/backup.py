from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.infrastructure.postgres.database import PostgresDatabase


ENCRYPTION_KEY_NOTICE = (
    "Model API keys stored in model_connections remain Fernet-encrypted. "
    "Back up SETTINGS_ENCRYPTION_KEY separately in a safe offline location."
)


@dataclass(frozen=True)
class DatabaseBackup:
    path: Path | None
    checksum: str | None
    bytes: int
    integrity_check: str
    schema_version: int | None
    user_count: int
    model_connection_count: int
    agent_run_count: int = 0
    rag_active_release: str | None = None
    backup_format: str = "logical_snapshot"


def verify_postgres_database(database: PostgresDatabase) -> DatabaseBackup:
    with database.connection() as conn:
        ping = conn.execute("SELECT 1").fetchone()
        if ping is None or ping[0] != 1:
            raise RuntimeError("PostgreSQL health probe returned unexpected result")

        schema_version: int | None = None
        if _table_exists(conn, "schema_migrations"):
            row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            if row is not None and row[0] is not None:
                schema_version = int(row[0])

        user_count = _table_count(conn, "users")
        model_count = _table_count(conn, "model_connections")
        agent_run_count = _table_count(conn, "agent_runs")

        rag_active_release: str | None = None
        if _table_exists(conn, "rag_active_pointer"):
            row = conn.execute(
                "SELECT active_release_id FROM rag_active_pointer WHERE slot = 'default'"
            ).fetchone()
            if row is not None:
                rag_active_release = str(row[0])

    return DatabaseBackup(
        path=None,
        checksum=None,
        bytes=0,
        integrity_check="ok",
        schema_version=schema_version,
        user_count=user_count,
        model_connection_count=model_count,
        agent_run_count=agent_run_count,
        rag_active_release=rag_active_release,
        backup_format="live_verify",
    )


def backup_postgres_database(
    database: PostgresDatabase,
    destination: Path,
    *,
    prefer_pg_dump: bool = True,
) -> DatabaseBackup:
    target = Path(destination).resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    status = verify_postgres_database(database)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    backup_format = "logical_snapshot"

    try:
        pg_dump_bin = shutil.which("pg_dump") if prefer_pg_dump else None
        if pg_dump_bin and target.suffix in {".dump", ".sql"}:
            cmd = [
                pg_dump_bin,
                "--no-owner",
                "--no-privileges",
                "--schema",
                database.target_schema,
                "--format=custom" if target.suffix == ".dump" else "--format=plain",
                "--file",
                str(temporary),
                database.dsn,
            ]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            backup_format = "pg_dump_custom" if target.suffix == ".dump" else "pg_dump_plain"
        else:
            snapshot = _export_logical_snapshot(database, status)
            temporary.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()

    content = target.read_bytes()
    return DatabaseBackup(
        path=target,
        checksum=hashlib.sha256(content).hexdigest(),
        bytes=len(content),
        integrity_check="ok",
        schema_version=status.schema_version,
        user_count=status.user_count,
        model_connection_count=status.model_connection_count,
        agent_run_count=status.agent_run_count,
        rag_active_release=status.rag_active_release,
        backup_format=backup_format,
    )


def verify_backup_file(backup_path: Path) -> DatabaseBackup:
    target = Path(backup_path).resolve(strict=True)
    if not target.is_file():
        raise FileNotFoundError(f"Backup file does not exist: {target}")
    raw = target.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    if target.suffix == ".json" or raw.lstrip().startswith(b"{"):
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or "tables" not in payload or "schema_version" not in payload:
            raise ValueError("Invalid FitLife PostgreSQL logical backup payload")
        tables = payload["tables"]
        return DatabaseBackup(
            path=target,
            checksum=checksum,
            bytes=len(raw),
            integrity_check="ok",
            schema_version=payload.get("schema_version"),
            user_count=len(tables.get("users", [])),
            model_connection_count=len(tables.get("model_connections", [])),
            agent_run_count=len(tables.get("agent_runs", [])),
            rag_active_release=payload.get("rag_active_release"),
            backup_format="logical_snapshot",
        )
    if not raw:
        raise ValueError("Backup file is empty")
    return DatabaseBackup(
        path=target,
        checksum=checksum,
        bytes=len(raw),
        integrity_check="ok",
        schema_version=None,
        user_count=0,
        model_connection_count=0,
        backup_format="pg_dump",
    )


def _export_logical_snapshot(database: PostgresDatabase, status: DatabaseBackup) -> dict:
    tables_data: dict[str, list[dict]] = {}
    with database.connection() as conn:
        conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        table_rows = conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = ? AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            (database.target_schema,),
        ).fetchall()
        for row in table_rows:
            table_name = str(row[0])
            col_rows = conn.execute(
                """
                SELECT column_name, udt_name
                FROM information_schema.columns
                WHERE table_schema = ? AND table_name = ?
                ORDER BY ordinal_position
                """,
                (database.target_schema, table_name),
            ).fetchall()
            select_cols = ", ".join(
                f'"{col}"' if udt != "vector" else f'"{col}"::text AS "{col}"'
                for col, udt in col_rows
            )
            if not select_cols:
                tables_data[table_name] = []
                continue
            rows = conn.execute(f'SELECT {select_cols} FROM "{table_name}"').fetchall()
            tables_data[table_name] = [dict(r) for r in rows]
        conn.rollback()

    return {
        "format": "fitlife-postgres-snapshot-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "schema": database.target_schema,
        "schema_version": status.schema_version,
        "rag_active_release": status.rag_active_release,
        "tables": tables_data,
    }


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = current_schema() AND table_name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _table_count(conn, table_name: str) -> int:
    if not _table_exists(conn, table_name):
        return 0
    row = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
    return int(row[0]) if row is not None else 0
