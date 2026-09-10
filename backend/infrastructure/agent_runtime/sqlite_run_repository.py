"""Dedicated runtime database; business migrations are intentionally independent."""
import json
import sqlite3
from dataclasses import asdict, fields
from contextlib import contextmanager
from pathlib import Path

from backend.agent.contracts import AgentRunSnapshot
from backend.agent.persistence import InvalidTransition, RunEvent, next_snapshot, safe_payload


class SQLiteRunRepository:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError("Unsupported runtime database schema")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                    user_id TEXT, operation TEXT NOT NULL, status TEXT NOT NULL,
                    current_step TEXT, attempt INTEGER NOT NULL, public_error_code TEXT,
                    created_at TEXT NOT NULL, started_at TEXT, deadline_at TEXT NOT NULL,
                    finished_at TEXT, policy_version TEXT NOT NULL, policy_snapshot_json TEXT NOT NULL,
                    provider TEXT, model TEXT, input_chars INTEGER NOT NULL,
                    input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, tool_calls INTEGER NOT NULL,
                    internal_error_id TEXT, failure_stage TEXT, version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_run_events (
                    run_id TEXT NOT NULL, seq INTEGER NOT NULL, event_type TEXT NOT NULL,
                    step TEXT, attempt INTEGER, occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL, PRIMARY KEY(run_id, seq)
                );
            """)
            connection.execute("PRAGMA user_version=1")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _get(connection, run_id, user_id):
        row = connection.execute("SELECT * FROM agent_runs WHERE id=? AND user_id IS ?", (run_id, user_id)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return AgentRunSnapshot(**dict(zip((field.name for field in fields(AgentRunSnapshot)), row)))

    @staticmethod
    def _append(connection, event):
        connection.execute("INSERT INTO agent_run_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (event.run_id, event.seq, event.event_type, event.step, event.attempt,
                            event.occurred_at, json.dumps(dict(event.payload), allow_nan=False)))

    def create(self, run):
        if run.status != "accepted" or run.version != 1:
            raise InvalidTransition("New run must be accepted")
        with self.connect() as connection:
            values = tuple(asdict(run).values())
            connection.execute("INSERT INTO agent_runs VALUES (" + ",".join("?" for _ in values) + ")", values)
            self._append(connection, RunEvent(run.run_id, 1, "RUN_ACCEPTED"))
        return run

    def get(self, run_id, user_id):
        with self.connect() as connection:
            return self._get(connection, run_id, user_id)

    def update(self, run, event_type, payload=None):
        payload = safe_payload(payload or {})
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._get(connection, run.run_id, run.user_id)
            updated = next_snapshot(current, run, event_type)
            values = asdict(updated)
            assignments = ",".join(("id" if name == "run_id" else name) + "=?" for name in values)
            connection.execute("UPDATE agent_runs SET " + assignments + " WHERE id=? AND version=?",
                               (*values.values(), run.run_id, current.version))
            self._append(connection, RunEvent(run.run_id, updated.version, event_type,
                                              run.current_step, run.attempt, payload=payload))
        return updated

    def events(self, run_id, user_id):
        with self.connect() as connection:
            self._get(connection, run_id, user_id)
            rows = connection.execute("SELECT run_id, seq, event_type, step, attempt, occurred_at, payload_json FROM agent_run_events WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
        return tuple(RunEvent(*row[:6], payload=json.loads(row[6])) for row in rows)
