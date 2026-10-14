"""Read approved runtime metadata from the isolated worker only."""
import sqlite3
from pathlib import Path


def runtime_metrics(root):
    path = Path(root) / "agent_runtime.sqlite3"
    if not path.exists():
        return {"run_ids": [], "policy_version": None, "retries": 0, "run_succeeded": False, "started_at": None, "finished_at": None}
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT id,policy_version,attempt,started_at,finished_at,status,policy_snapshot_json FROM agent_runs").fetchall()
        retries = connection.execute("SELECT COUNT(*) FROM agent_run_events WHERE event_type='STEP_RETRY_SCHEDULED'").fetchone()[0]
    versions = {row[1] for row in rows}
    from backend.task_evaluation.provenance import fingerprint
    snapshots = sorted({row[6] for row in rows})
    return {"run_ids": [row[0] for row in rows],
            "policy_config_digest": fingerprint(snapshots) if snapshots else None,
            "started_at": min((row[3] for row in rows if row[3]), default=None),
            "finished_at": max((row[4] for row in rows if row[4]), default=None),
            "run_succeeded": bool(rows) and all(row[5] == "succeeded" for row in rows),
            "policy_version": next(iter(versions)) if len(versions) == 1 else None,
            "retries": retries}
