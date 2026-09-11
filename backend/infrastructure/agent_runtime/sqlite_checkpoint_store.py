"""Validated recovery state, never an automatic replay mechanism."""
import json

from backend.agent.persistence import Checkpoint, InvalidTransition, TERMINAL_STATUSES, safe_checkpoint


class SQLiteCheckpointStore:
    def __init__(self, repository):
        self.repository = repository
        with repository.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS agent_checkpoints (
                run_id TEXT NOT NULL, name TEXT NOT NULL, state_json TEXT NOT NULL,
                version INTEGER NOT NULL, PRIMARY KEY(run_id, name))""")

    def save(self, run_id, user_id, name, state):
        state = safe_checkpoint(state)
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = self.repository._get(connection, run_id, user_id)
            if run.status in TERMINAL_STATUSES:
                raise InvalidTransition("Cannot checkpoint a terminal run")
            row = connection.execute("SELECT version FROM agent_checkpoints WHERE run_id=? AND name=?", (run_id, name)).fetchone()
            version = row[0] + 1 if row else 1
            connection.execute("INSERT OR REPLACE INTO agent_checkpoints VALUES (?, ?, ?, ?)",
                               (run_id, name, json.dumps(state), version))
        return Checkpoint(run_id, name, state, version)

    def get(self, run_id, user_id, name):
        with self.repository.connect() as connection:
            self.repository._get(connection, run_id, user_id)
            row = connection.execute("SELECT state_json, version FROM agent_checkpoints WHERE run_id=? AND name=?", (run_id, name)).fetchone()
            if row is None:
                raise KeyError(name)
        return Checkpoint(run_id, name, safe_checkpoint(json.loads(row[0])), row[1])
