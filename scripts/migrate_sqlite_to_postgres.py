"""Migrate a read-only SQLite snapshot into PostgreSQL (with parity verification)."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from backend.infrastructure.postgres.database import PostgresDatabase
from backend.infrastructure.postgres.migrations import run_migrations
from backend.infrastructure.postgres.schema import RECORDS_MIGRATIONS

_BUSINESS_TABLE_ORDER: tuple[str, ...] = (
    "data_migrations",
    "users",
    "user_preferences",
    "model_connections",
    "user_profile_versions",
    "overall_goal_versions",
    "daily_target_versions",
    "daily_logs",
    "profile_safety_versions",
    "body_measurements",
    "user_training_context",
    "food_catalog",
    "exercise_catalog",
    "catalog_aliases",
    "catalog_favorites",
    "catalog_usage",
    "catalog_imports",
    "catalog_search",
    "record_drafts",
    "entry_interaction_commands",
    "entry_item_commits",
    "meals",
    "meal_items",
    "training_sessions",
    "strength_exercises",
    "strength_sets",
    "cardio_items",
    "idempotency_keys",
    "task_budgets",
    "task_budget_operations",
    "coach_conversations",
    "coach_turns",
    "coach_messages",
    "plans",
    "plan_heads",
    "plan_drafts",
    "plan_activation_receipts",
    "plan_import_state",
    "plan_adjustment_sessions",
    "plan_task_permissions",
    "plan_repair_rounds",
    "plan_candidate_submissions",
    "plan_task_receipts",
    "plan_cycles",
    "plan_days",
    "weekly_automation_runs",
)

_RUNTIME_TABLE_ORDER: tuple[str, ...] = (
    "agent_runs",
    "agent_run_events",
    "agent_checkpoints",
)

_JSONB_CAST_COLUMNS: dict[str, set[str]] = {
    "agent_run_events": {"payload_json"},
    "agent_checkpoints": {"state_json"},
}


def _open_readonly_sqlite(path: Path) -> sqlite3.Connection:
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_file():
        raise FileNotFoundError(f"SQLite file does not exist: {resolved}")
    conn = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if str(integrity) != "ok":
        conn.close()
        raise sqlite3.DatabaseError(f"SQLite integrity_check failed for {resolved}: {integrity}")
    return conn


def _sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


def _sqlite_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    return [str(row[1]) for row in rows]


def _pg_writable_columns(pg_conn, schema_name: str, table_name: str) -> list[str]:
    rows = pg_conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = ?
          AND table_name = ?
          AND COALESCE(is_generated, 'NEVER') = 'NEVER'
        ORDER BY ordinal_position
        """,
        (schema_name, table_name),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _copy_tables(
    sqlite_conn: sqlite3.Connection,
    pg_conn,
    *,
    schema_name: str,
    table_order: tuple[str, ...],
) -> dict[str, dict[str, int]]:
    present = _sqlite_tables(sqlite_conn)
    report: dict[str, dict[str, int]] = {}

    for table in table_order:
        if table not in present:
            continue
        sqlite_cols = _sqlite_columns(sqlite_conn, table)
        pg_cols = _pg_writable_columns(pg_conn, schema_name, table)
        if not pg_cols:
            continue

        # Handle legacy `run_id` -> `id` rename on agent_runs if present.
        column_map: list[tuple[str, str]] = []
        pg_col_set = set(pg_cols)
        for src_col in sqlite_cols:
            dst_col = "id" if (table == "agent_runs" and src_col == "run_id" and "id" in pg_col_set) else src_col
            if dst_col in pg_col_set:
                column_map.append((src_col, dst_col))
        if not column_map:
            continue

        src_sql = ", ".join(f'"{src}"' for src, _ in column_map)
        rows = sqlite_conn.execute(f'SELECT {src_sql} FROM "{table}"').fetchall()
        source_count = len(rows)

        if source_count > 0:
            jsonb_cols = _JSONB_CAST_COLUMNS.get(table, set())
            dst_sql = ", ".join(f'"{dst}"' for _, dst in column_map)
            placeholders = ", ".join(
                "?::jsonb" if dst in jsonb_cols else "?"
                for _, dst in column_map
            )
            insert_sql = (
                f'INSERT INTO "{table}" ({dst_sql}) VALUES ({placeholders}) '
                "ON CONFLICT DO NOTHING"
            )
            batch = [tuple(row[idx] for idx in range(len(column_map))) for row in rows]
            pg_conn.executemany(insert_sql, batch)

        target_count = int(pg_conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        if target_count < source_count:
            raise RuntimeError(
                f"Parity check failed for {table}: source={source_count}, target={target_count}"
            )
        report[table] = {"source": source_count, "target": target_count}

    if "idempotency_keys" in report:
        pg_conn.execute(
            """
            SELECT setval(
                pg_get_serial_sequence('idempotency_keys', 'id'),
                COALESCE((SELECT MAX(id) FROM idempotency_keys), 1),
                (SELECT COUNT(*) > 0 FROM idempotency_keys)
            )
            """
        )
    return report


def migrate_sqlite_to_postgres(
    *,
    sqlite_path: Path,
    database: PostgresDatabase,
    runtime_sqlite_path: Path | None = None,
    apply: bool = False,
) -> dict:
    business_conn = _open_readonly_sqlite(sqlite_path)
    runtime_conn = _open_readonly_sqlite(runtime_sqlite_path) if runtime_sqlite_path is not None else None
    try:
        if not apply:
            present = _sqlite_tables(business_conn)
            counts = {
                table: int(business_conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                for table in _BUSINESS_TABLE_ORDER
                if table in present
            }
            if runtime_conn is not None:
                rt_present = _sqlite_tables(runtime_conn)
                for table in _RUNTIME_TABLE_ORDER:
                    if table in rt_present:
                        counts[table] = int(
                            runtime_conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                        )
            return {
                "mode": "dry_run",
                "source": str(Path(sqlite_path).resolve()),
                "runtime_source": str(Path(runtime_sqlite_path).resolve()) if runtime_sqlite_path else None,
                "target_schema": database.target_schema,
                "source_counts": counts,
            }

        run_migrations(database, RECORDS_MIGRATIONS)
        with database.transaction() as pg_conn:
            tables_report = _copy_tables(
                business_conn,
                pg_conn,
                schema_name=database.target_schema,
                table_order=_BUSINESS_TABLE_ORDER,
            )
            if runtime_conn is not None:
                tables_report.update(
                    _copy_tables(
                        runtime_conn,
                        pg_conn,
                        schema_name=database.target_schema,
                        table_order=_RUNTIME_TABLE_ORDER,
                    )
                )
        return {
            "mode": "apply",
            "source": str(Path(sqlite_path).resolve()),
            "runtime_source": str(Path(runtime_sqlite_path).resolve()) if runtime_sqlite_path else None,
            "target_schema": database.target_schema,
            "schema_version": RECORDS_MIGRATIONS[-1].version,
            "tables": tables_report,
        }
    finally:
        business_conn.close()
        if runtime_conn is not None:
            runtime_conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate a read-only SQLite DB into PostgreSQL")
    parser.add_argument("--sqlite", required=True, type=Path, help="Path to source SQLite snapshot")
    parser.add_argument("--runtime-sqlite", type=Path, default=None, help="Optional agent_runtime.sqlite3 snapshot")
    parser.add_argument("--database-url", type=str, default=None)
    parser.add_argument("--schema", type=str, default=None)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    database = PostgresDatabase(
        args.database_url or settings.database_url,
        schema=args.schema or settings.database_schema,
    )
    summary = migrate_sqlite_to_postgres(
        sqlite_path=args.sqlite,
        database=database,
        runtime_sqlite_path=args.runtime_sqlite,
        apply=bool(args.apply),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
