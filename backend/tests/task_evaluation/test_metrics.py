from backend.task_evaluation.metrics import runtime_metrics


def test_retry_events_and_policy_are_distinct_from_rules(make_isolated_pg_db):
    database = make_isolated_pg_db(initialize=False)
    with database.transaction() as db:
        db.execute("CREATE TABLE agent_runs(id TEXT, policy_version TEXT, attempt INTEGER, started_at TEXT, finished_at TEXT, status TEXT, policy_snapshot_json TEXT)")
        db.execute("CREATE TABLE agent_run_events(event_type TEXT)")
        db.execute("INSERT INTO agent_runs VALUES('synthetic','policy-3',1,'start','finish','succeeded','{}')")
        db.executemany("INSERT INTO agent_run_events VALUES(?)", [("STEP_RETRY_SCHEDULED",), ("STEP_RETRY_SCHEDULED",), ("STEP_SUCCEEDED",)])
    metrics = runtime_metrics(database)
    assert metrics["retries"] == 2
    assert metrics["policy_version"] == "policy-3"
    assert "rule_version" not in metrics
    assert metrics["run_succeeded"] is True
    assert metrics["policy_config_digest"]


def test_missing_runtime_is_unknown_policy_and_no_run(make_isolated_pg_db):
    database = make_isolated_pg_db(initialize=False)
    assert runtime_metrics(database)["policy_version"] is None
    assert runtime_metrics(database)["run_succeeded"] is False
