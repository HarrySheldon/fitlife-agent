"""Authoritative PostgreSQL repository for agent runs and append-only events."""
from __future__ import annotations

import json
from dataclasses import asdict, fields
from typing import Any

from backend.agent.contracts import AgentRunSnapshot
from backend.agent.persistence import (
    InvalidTransition,
    RunEvent,
    VersionConflict,
    next_snapshot,
    safe_payload,
)
from backend.infrastructure.postgres.database import PostgresDatabase
from backend.infrastructure.postgres.errors import DatabaseIntegrityError


def _decode_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value is None or value == "":
        return {}
    parsed = json.loads(value)
    return dict(parsed) if isinstance(parsed, dict) else {}


class PostgresRunRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    @staticmethod
    def _snapshot_fields() -> tuple[str, ...]:
        return tuple(field.name for field in fields(AgentRunSnapshot))

    @classmethod
    def _get(
        cls,
        connection,
        run_id: str,
        user_id: str | None,
        *,
        for_update: bool = False,
    ) -> AgentRunSnapshot:
        names = cls._snapshot_fields()
        columns = ",".join("id" if name == "run_id" else name for name in names)
        suffix = " FOR UPDATE" if for_update else ""
        row = connection.execute(
            f"SELECT {columns} FROM agent_runs WHERE id = ? AND user_id IS NOT DISTINCT FROM ?{suffix}",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return AgentRunSnapshot(**dict(zip(names, row)))

    @staticmethod
    def _append(connection, event: RunEvent) -> None:
        connection.execute(
            """
            INSERT INTO agent_run_events (
                run_id, seq, event_type, step, attempt, occurred_at, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?::jsonb)
            """,
            (
                event.run_id,
                event.seq,
                event.event_type,
                event.step,
                event.attempt,
                event.occurred_at,
                json.dumps(dict(event.payload), allow_nan=False),
            ),
        )

    def create(self, run: AgentRunSnapshot) -> AgentRunSnapshot:
        if run.status != "accepted" or run.version != 1:
            raise InvalidTransition("New run must be accepted")
        data = asdict(run)
        columns = ",".join("id" if name == "run_id" else name for name in data)
        placeholders = ",".join("?" for _ in data)
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    f"INSERT INTO agent_runs ({columns}) VALUES ({placeholders})",
                    tuple(data.values()),
                )
                self._append(connection, RunEvent(run.run_id, 1, "RUN_ACCEPTED"))
        except DatabaseIntegrityError as error:
            raise InvalidTransition("Run already exists") from error
        return run

    def get(self, run_id: str, user_id: str | None) -> AgentRunSnapshot:
        with self.database.connection() as connection:
            return self._get(connection, run_id, user_id)

    def update(
        self,
        run: AgentRunSnapshot,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> AgentRunSnapshot:
        validated_payload = safe_payload(payload or {})
        with self.database.transaction() as connection:
            current = self._get(connection, run.run_id, run.user_id, for_update=True)
            updated = next_snapshot(current, run, event_type)
            values = asdict(updated)
            assignments = ",".join(
                ("id" if name == "run_id" else name) + "=?" for name in values
            )
            cursor = connection.execute(
                f"UPDATE agent_runs SET {assignments} WHERE id = ? AND version = ?",
                (*values.values(), run.run_id, current.version),
            )
            if cursor.rowcount != 1:
                raise VersionConflict("Stale run version")
            self._append(
                connection,
                RunEvent(
                    run.run_id,
                    updated.version,
                    event_type,
                    run.current_step,
                    run.attempt,
                    payload=validated_payload,
                ),
            )
        return updated

    def events(self, run_id: str, user_id: str | None) -> tuple[RunEvent, ...]:
        with self.database.connection() as connection:
            self._get(connection, run_id, user_id)
            rows = connection.execute(
                """
                SELECT run_id, seq, event_type, step, attempt, occurred_at, payload_json
                FROM agent_run_events
                WHERE run_id = ?
                ORDER BY seq ASC
                """,
                (run_id,),
            ).fetchall()
        return tuple(
            RunEvent(
                row["run_id"],
                int(row["seq"]),
                row["event_type"],
                row["step"],
                row["attempt"],
                row["occurred_at"],
                payload=_decode_json(row["payload_json"]),
            )
            for row in rows
        )

    def list_recoverable(
        self,
        user_id: str | None = None,
        *,
        limit: int = 50,
    ) -> tuple[AgentRunSnapshot, ...]:
        names = self._snapshot_fields()
        columns = ",".join(
            ("r.id" if name == "run_id" else f"r.{name}") for name in names
        )
        where = [
            "r.status IN ('running', 'failed', 'timed_out', 'cancelled')",
            "EXISTS (SELECT 1 FROM agent_checkpoints AS c WHERE c.run_id = r.id)",
        ]
        params: list[object] = []
        if user_id is not None:
            where.append("r.user_id = ?")
            params.append(user_id)
        params.append(max(1, int(limit)))
        sql = f"""
            SELECT {columns}
            FROM agent_runs AS r
            WHERE {' AND '.join(where)}
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT ?
        """
        with self.database.connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return tuple(AgentRunSnapshot(**dict(zip(names, row))) for row in rows)
