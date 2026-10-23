"""Read approved runtime metadata from the isolated worker only."""
import sqlite3
import json
from pathlib import Path


def runtime_metrics(root):
    path = Path(root) / "agent_runtime.sqlite3"
    if not path.exists():
        return {"run_ids": [], "policy_version": None, "retries": 0, "run_succeeded": False, "started_at": None, "finished_at": None}
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT id,policy_version,attempt,started_at,finished_at,status,policy_snapshot_json FROM agent_runs").fetchall()
        retries = connection.execute("SELECT COUNT(*) FROM agent_run_events WHERE event_type='STEP_RETRY_SCHEDULED'").fetchone()[0]
        columns = {row[1] for row in connection.execute('PRAGMA table_info(agent_run_events)')}
        decisions = ([{**json.loads(row[1]), '_run_id': row[0]} for row in connection.execute(
            "SELECT run_id,payload_json FROM agent_run_events WHERE event_type='AGENT_TOOL_DECIDED'")]
            if 'payload_json' in columns else [])
        progress = ([{**json.loads(row[1]), '_run_id': row[0]} for row in connection.execute(
            "SELECT run_id,payload_json FROM agent_run_events WHERE event_type='AGENT_PROGRESS'")]
            if 'payload_json' in columns else [])
    versions = {row[1] for row in rows}
    from backend.task_evaluation.provenance import fingerprint
    snapshots = sorted({row[6] for row in rows})
    def total_run_max(items, field):
        values = {}
        for item in items:
            key = item['_run_id']
            values[key] = max(values.get(key, 0), item.get(field, 0))
        return sum(values.values())
    return {"run_ids": [row[0] for row in rows],
            "tool_attempts": len(decisions),
            "tool_denials": sum(item.get('outcome') == 'refuse' for item in decisions),
            "cache_hits": sum(item.get('cache_hits', 0) for item in decisions),
            "decision_count": total_run_max(progress, 'decision_count'),
            "protocol_failures": total_run_max(progress, 'protocol_failures'),
            "tool_executions": total_run_max(decisions, 'tool_executions'),
            "context_chars": max((item.get('context_chars', 0) for item in progress), default=0),
            "loaded_skill_ids": sorted({resource for item in progress for resource in item.get('loaded_skill_ids', [])}),
            "resource_releases": sorted({item['resource_release'] for item in decisions if item.get('resource_release')}),
            "policy_config_digest": fingerprint(snapshots) if snapshots else None,
            "started_at": min((row[3] for row in rows if row[3]), default=None),
            "finished_at": max((row[4] for row in rows if row[4]), default=None),
            "run_succeeded": bool(rows) and all(row[5] == "succeeded" for row in rows),
            "policy_version": next(iter(versions)) if len(versions) == 1 else None,
            "retries": retries}
