import sqlite3
from backend.task_evaluation.metrics import runtime_metrics


def test_retry_events_and_policy_are_distinct_from_rules(tmp_path):
    with sqlite3.connect(tmp_path / "agent_runtime.sqlite3") as db:
        db.execute("CREATE TABLE agent_runs(id,policy_version,attempt,started_at,finished_at,status,policy_snapshot_json)")
        db.execute("CREATE TABLE agent_run_events(event_type)")
        db.execute("INSERT INTO agent_runs VALUES('synthetic','policy-3',1,'start','finish','succeeded','{}')")
        db.executemany("INSERT INTO agent_run_events VALUES(?)", [("STEP_RETRY_SCHEDULED",), ("STEP_RETRY_SCHEDULED",), ("STEP_SUCCEEDED",)])
    metrics = runtime_metrics(tmp_path)
    assert metrics["retries"] == 2
    assert metrics["policy_version"] == "policy-3"
    assert "rule_version" not in metrics
    assert metrics["run_succeeded"] is True
    assert metrics["policy_config_digest"]


def test_missing_runtime_is_unknown_policy_and_no_run(tmp_path):
    assert runtime_metrics(tmp_path)["policy_version"] is None
    assert runtime_metrics(tmp_path)["run_succeeded"] is False
