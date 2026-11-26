"""Phase 3 tests for read-only SQLite -> PostgreSQL snapshot migration and verification."""
from __future__ import annotations

import json
import sqlite3

from backend.agent.persistence import safe_checkpoint
from backend.infrastructure.agent_runtime.postgres_checkpoint_store import (
    PostgresCheckpointStore,
)
from backend.infrastructure.agent_runtime.postgres_run_repository import (
    PostgresRunRepository,
)
from backend.infrastructure.postgres.backup import (
    backup_postgres_database,
    verify_backup_file,
    verify_postgres_database,
)
from scripts.migrate_sqlite_to_postgres import migrate_sqlite_to_postgres


def _create_sample_sqlite_snapshots(tmp_path):
    biz_path = tmp_path / "biz.sqlite3"
    with sqlite3.connect(biz_path) as conn:
        conn.executescript(
            """
            CREATE TABLE users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                email TEXT,
                phone TEXT,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                token_version INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE user_preferences (
                user_id TEXT PRIMARY KEY REFERENCES users(user_id),
                language TEXT NOT NULL,
                unit_system TEXT NOT NULL,
                timezone TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE idempotency_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO users VALUES ('u1', 'mig', NULL, NULL, 'Migrated User', 'h', 1, '2026-01-01T00:00:00Z');
            INSERT INTO user_preferences VALUES ('u1', 'zh-CN', 'metric', 'Asia/Shanghai', '2026-01-01T00:00:00Z');
            INSERT INTO idempotency_keys VALUES (7, 'u1', 'op1', 'k1', '{"ok":true}', '2026-01-01T00:00:00Z');
            """
        )

    rt_path = tmp_path / "rt.sqlite3"
    with sqlite3.connect(rt_path) as conn:
        conn.executescript(
            """
            CREATE TABLE agent_runs (
                run_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL UNIQUE,
                user_id TEXT,
                operation TEXT NOT NULL,
                status TEXT NOT NULL,
                current_step TEXT,
                attempt INTEGER NOT NULL,
                public_error_code TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                deadline_at TEXT NOT NULL,
                finished_at TEXT,
                policy_version TEXT NOT NULL,
                policy_snapshot_json TEXT NOT NULL,
                provider TEXT,
                model TEXT,
                input_chars INTEGER NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                tool_calls INTEGER NOT NULL,
                internal_error_id TEXT,
                failure_stage TEXT,
                version INTEGER NOT NULL,
                task_id TEXT,
                task_version INTEGER
            );
            CREATE TABLE agent_run_events (
                run_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                step TEXT,
                attempt INTEGER,
                occurred_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (run_id, seq)
            );
            CREATE TABLE agent_checkpoints (
                run_id TEXT NOT NULL,
                name TEXT NOT NULL,
                state_json TEXT NOT NULL,
                version INTEGER NOT NULL,
                PRIMARY KEY (run_id, name)
            );
            INSERT INTO agent_runs VALUES (
                'run-mig-1', 'req-mig-1', 'u1', 'chat', 'running', 'planner', 1, NULL,
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z', '2026-01-01T00:01:00Z', NULL,
                'policy-1', '{}', 'mock', 'test', 10, 5, 0, 0, NULL, NULL, 1, NULL, NULL
            );
            INSERT INTO agent_run_events VALUES (
                'run-mig-1', 1, 'RUN_ACCEPTED', NULL, NULL, '2026-01-01T00:00:00Z', '{}'
            );
            INSERT INTO agent_checkpoints VALUES (
                'run-mig-1', 'planner', '{"completed": true, "attempt": 1}', 1
            );
            """
        )
    return biz_path, rt_path


def test_sqlite_to_postgres_migration_dry_run_apply_idempotency_and_backup_verify(
    tmp_path,
    make_isolated_pg_db,
):
    biz_path, rt_path = _create_sample_sqlite_snapshots(tmp_path)
    pg_db = make_isolated_pg_db(initialize=False)

    dry = migrate_sqlite_to_postgres(
        sqlite_path=biz_path,
        runtime_sqlite_path=rt_path,
        database=pg_db,
        apply=False,
    )
    assert dry["mode"] == "dry_run"
    assert dry["source_counts"]["users"] == 1
    assert dry["source_counts"]["agent_runs"] == 1

    applied = migrate_sqlite_to_postgres(
        sqlite_path=biz_path,
        runtime_sqlite_path=rt_path,
        database=pg_db,
        apply=True,
    )
    assert applied["mode"] == "apply"
    assert applied["tables"]["users"] == {"source": 1, "target": 1}
    assert applied["tables"]["agent_runs"] == {"source": 1, "target": 1}
    assert applied["tables"]["agent_checkpoints"] == {"source": 1, "target": 1}

    # Re-running apply is idempotent (ON CONFLICT DO NOTHING)
    reapplied = migrate_sqlite_to_postgres(
        sqlite_path=biz_path,
        runtime_sqlite_path=rt_path,
        database=pg_db,
        apply=True,
    )
    assert reapplied["tables"]["users"] == {"source": 1, "target": 1}

    # Sequence on idempotency_keys was synced past id=7 so new inserts get id >= 8
    with pg_db.transaction() as conn:
        row = conn.execute(
            """
            INSERT INTO idempotency_keys (user_id, operation, idempotency_key, response_json, created_at)
            VALUES ('u1', 'op2', 'k2', '{"ok":true}', '2026-01-01T00:00:01Z')
            RETURNING id
            """
        ).fetchone()
    assert int(row["id"]) >= 8

    # Runtime repositories read migrated JSONB events and checkpoints cleanly
    run_repo = PostgresRunRepository(pg_db)
    cp_store = PostgresCheckpointStore(run_repo)
    assert run_repo.get("run-mig-1", "u1").status == "running"
    assert run_repo.events("run-mig-1", "u1")[0].event_type == "RUN_ACCEPTED"
    cp = cp_store.get("run-mig-1", "u1", "planner")
    assert cp.state == safe_checkpoint({"completed": True, "attempt": 1})

    # Live verification + backup file export & verify
    live_check = verify_postgres_database(pg_db)
    assert live_check.integrity_check == "ok"
    assert live_check.user_count == 1
    assert live_check.agent_run_count == 1

    backup_path = tmp_path / "pg_backup.json"
    written = backup_postgres_database(pg_db, backup_path)
    verified = verify_backup_file(written.path)
    assert verified.checksum == written.checksum
    assert verified.user_count == 1
    assert verified.integrity_check == "ok"
    parsed = json.loads(backup_path.read_text(encoding="utf-8"))
    assert parsed["tables"]["users"][0]["user_id"] == "u1"
