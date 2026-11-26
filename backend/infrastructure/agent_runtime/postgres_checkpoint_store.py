"""PostgreSQL checkpoint store for step-level recovery metadata."""
from __future__ import annotations

import json
from typing import Any

from backend.agent.persistence import (
    TERMINAL_STATUSES,
    Checkpoint,
    InvalidTransition,
    safe_checkpoint,
)
from backend.infrastructure.agent_runtime.postgres_run_repository import (
    PostgresRunRepository,
)


def _decode_state(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value is None or value == "":
        return {}
    parsed = json.loads(value)
    return dict(parsed) if isinstance(parsed, dict) else {}


class PostgresCheckpointStore:
    def __init__(self, repository: PostgresRunRepository) -> None:
        self.repository = repository

    def save(
        self,
        run_id: str,
        user_id: str | None,
        name: str,
        state: dict[str, object] | Any,
        *,
        step_index: int = 0,
        checkpoint_kind: str = "step",
    ) -> Checkpoint:
        validated = safe_checkpoint(state)
        with self.repository.database.transaction() as connection:
            run = self.repository._get(connection, run_id, user_id, for_update=True)
            if run.status in TERMINAL_STATUSES:
                raise InvalidTransition("Cannot checkpoint a terminal run")
            row = connection.execute(
                """
                INSERT INTO agent_checkpoints (
                    run_id, name, step_index, checkpoint_kind, state_json, version, updated_at
                )
                VALUES (?, ?, ?, ?, ?::jsonb, 1, NOW())
                ON CONFLICT (run_id, name) DO UPDATE SET
                    step_index = EXCLUDED.step_index,
                    checkpoint_kind = EXCLUDED.checkpoint_kind,
                    state_json = EXCLUDED.state_json,
                    version = agent_checkpoints.version + 1,
                    updated_at = NOW()
                RETURNING version
                """,
                (
                    run_id,
                    name,
                    int(step_index),
                    checkpoint_kind,
                    json.dumps(validated, ensure_ascii=False, allow_nan=False),
                ),
            ).fetchone()
            version = int(row["version"])
        return Checkpoint(
            run_id,
            name,
            validated,
            version,
            step_index=int(step_index),
            checkpoint_kind=checkpoint_kind,
        )

    def get(self, run_id: str, user_id: str | None, name: str) -> Checkpoint:
        with self.repository.database.connection() as connection:
            self.repository._get(connection, run_id, user_id)
            row = connection.execute(
                """
                SELECT state_json, version, step_index, checkpoint_kind
                FROM agent_checkpoints
                WHERE run_id = ? AND name = ?
                """,
                (run_id, name),
            ).fetchone()
            if row is None:
                raise KeyError(name)
        return Checkpoint(
            run_id,
            name,
            safe_checkpoint(_decode_state(row["state_json"])),
            int(row["version"]),
            step_index=int(row["step_index"]),
            checkpoint_kind=row["checkpoint_kind"],
        )

    load = get

    def latest(self, run_id: str, user_id: str | None) -> Checkpoint | None:
        with self.repository.database.connection() as connection:
            self.repository._get(connection, run_id, user_id)
            row = connection.execute(
                """
                SELECT name, state_json, version, step_index, checkpoint_kind
                FROM agent_checkpoints
                WHERE run_id = ?
                ORDER BY step_index DESC, version DESC, updated_at DESC, name DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return Checkpoint(
            run_id,
            row["name"],
            safe_checkpoint(_decode_state(row["state_json"])),
            int(row["version"]),
            step_index=int(row["step_index"]),
            checkpoint_kind=row["checkpoint_kind"],
        )

    def list_for_run(self, run_id: str, user_id: str | None) -> tuple[Checkpoint, ...]:
        with self.repository.database.connection() as connection:
            self.repository._get(connection, run_id, user_id)
            rows = connection.execute(
                """
                SELECT name, state_json, version, step_index, checkpoint_kind
                FROM agent_checkpoints
                WHERE run_id = ?
                ORDER BY step_index ASC, version ASC, name ASC
                """,
                (run_id,),
            ).fetchall()
        return tuple(
            Checkpoint(
                run_id,
                row["name"],
                safe_checkpoint(_decode_state(row["state_json"])),
                int(row["version"]),
                step_index=int(row["step_index"]),
                checkpoint_kind=row["checkpoint_kind"],
            )
            for row in rows
        )
