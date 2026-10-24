"""Read approved runtime metadata from the isolated worker only.

The event log is the durable record of what actually happened. Physical attempts
are derived from it rather than from completed decisions, because a handler that
started and was torn down has no decision to count and would otherwise look
identical to a handler that was never invoked.
"""
import sqlite3
import json
from pathlib import Path

from backend.task_evaluation.measurements import MEASURED_USAGE_SOURCES

_EMPTY = {
    "run_ids": [],
    "policy_version": None,
    "retries": 0,
    "run_succeeded": False,
    "started_at": None,
    "finished_at": None,
    "attempts_started": 0,
    "attempts_finished": 0,
    "attempts_incomplete": 0,
    "unknown_usage_count": 0,
    "known_total_tokens": 0,
    "usage_sources": [],
}


def _payloads(connection, event_type, columns):
    if "payload_json" not in columns:
        return []
    # Older runtime databases may predate a column; read what exists rather than
    # failing the whole report over a missing diagnostic field.
    if "run_id" in columns:
        rows = connection.execute(
            "SELECT run_id, payload_json FROM agent_run_events WHERE event_type=?",
            (event_type,),
        ).fetchall()
    else:
        rows = [(None, raw) for (raw,) in connection.execute(
            "SELECT payload_json FROM agent_run_events WHERE event_type=?",
            (event_type,),
        )]
    payloads = []
    for run_id, raw in rows:
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            value = {}
        payloads.append({**(value if isinstance(value, dict) else {}), "_run_id": run_id})
    return payloads


def _attempt_closure(connection, columns):
    """Started, finished and unfinished physical attempts, plus their usage."""
    started = connection.execute(
        "SELECT COUNT(*) FROM agent_run_events WHERE event_type='TOOL_STARTED'"
    ).fetchone()[0]
    finished = connection.execute(
        "SELECT COUNT(*) FROM agent_run_events WHERE event_type='TOOL_FINISHED'"
    ).fetchone()[0]
    started_payloads = _payloads(connection, "TOOL_STARTED", columns)
    finished_payloads = _payloads(connection, "TOOL_FINISHED", columns)

    started_ids = {
        payload["attempt_id"]
        for payload in started_payloads
        if isinstance(payload.get("attempt_id"), str)
    }
    finished_ids = {
        payload["attempt_id"]
        for payload in finished_payloads
        if isinstance(payload.get("attempt_id"), str)
    }
    # With trusted identifiers the gap is exact. Legacy logs only have counts,
    # so the difference is the best available lower bound.
    incomplete = len(started_ids - finished_ids) if started_ids else max(0, started - finished)

    sources = set()
    known_tokens = 0
    unknown = 0
    for payload in finished_payloads:
        source = payload.get("usage_source")
        input_tokens = payload.get("input_tokens")
        output_tokens = payload.get("output_tokens")
        if (source in MEASURED_USAGE_SOURCES and type(input_tokens) is int
                and type(output_tokens) is int):
            sources.add(source)
            known_tokens += input_tokens + output_tokens
        else:
            unknown += 1
    if "payload_json" not in columns:
        unknown = finished

    return {
        "attempts_started": started,
        "attempts_finished": finished,
        "attempts_incomplete": incomplete,
        "unknown_usage_count": unknown,
        "known_total_tokens": known_tokens,
        "usage_sources": sorted(sources),
    }


def runtime_metrics(root):
    path = Path(root) / "agent_runtime.sqlite3"
    if not path.exists():
        return dict(_EMPTY)
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT id,policy_version,attempt,started_at,finished_at,status,policy_snapshot_json FROM agent_runs").fetchall()
        retries = connection.execute("SELECT COUNT(*) FROM agent_run_events WHERE event_type='STEP_RETRY_SCHEDULED'").fetchone()[0]
        columns = {row[1] for row in connection.execute('PRAGMA table_info(agent_run_events)')}
        decisions = _payloads(connection, "AGENT_TOOL_DECIDED", columns)
        progress = _payloads(connection, "AGENT_PROGRESS", columns)
        attempts = _attempt_closure(connection, columns)
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
            "retries": retries,
            **attempts}
