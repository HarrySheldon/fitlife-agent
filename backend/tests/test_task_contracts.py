import pytest


def test_repair_round_limit_is_task_wide():
    from backend.agent.tasks.contracts import next_repair_round
    from backend.domain.errors import ApplicationError

    assert next_repair_round(0) == 1
    assert next_repair_round(1) == 2
    for invalid in (2, -1, True, 1.5, "1"):
        with pytest.raises(ValueError, match="REPAIR_LIMIT"):
            next_repair_round(invalid)


def test_values_replay_rounds_and_enforce_budget_and_versions():
    from backend.agent.tasks.contracts import TaskRef, TaskBudget, start_repair_round, next_task_version
    from backend.domain.errors import ApplicationError

    for value in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            TaskRef("task", value)
    assert next_task_version(1, 1) == 2
    with pytest.raises(ApplicationError) as error:
        next_task_version(2, 1)
    assert error.value.status_code == 409
    round_ = start_repair_round(None, "r1", {"diet", "training"}).complete("diet")
    assert start_repair_round(round_, "r1", {"diet", "training"}) is round_
    assert round_.complete("diet") is round_
    with pytest.raises(ApplicationError):
        start_repair_round(round_, "r1", {"diet"})
    second = start_repair_round(round_.complete("training"), "r2", {"diet"})
    with pytest.raises(ValueError, match="REPAIR_LIMIT"):
        start_repair_round(second.complete("diet"), "r3", {"training"})
    budget = TaskBudget(call_limit=2, token_limit=10).reserve(calls=1, tokens=10)
    with pytest.raises(ApplicationError) as error:
        budget.reserve(tokens=1)
    assert error.value.code == "TASK_BUDGET_EXHAUSTED"
    for value in (-1, True, 1.5):
        with pytest.raises(ValueError):
            TaskBudget(consumed_calls=value)


def test_link_defaults_and_partial_links_are_rejected():
    from backend.agent.contracts import AgentCommand, AgentRunSnapshot
    assert AgentCommand("chat", "q", "u").task_ref is None
    assert AgentRunSnapshot("r", "q", "u", "chat", "accepted").task_id is None
    for changes in ({"task_id": "task"}, {"task_version": 1},
                    {"task_id": "task", "task_version": True}):
        with pytest.raises(ValueError):
            AgentRunSnapshot("r", "q", "u", "chat", "accepted", **changes)


@pytest.mark.parametrize("code,status", [("TASK_NOT_FOUND", 404), ("TASK_VERSION_CONFLICT", 409),
    ("IDEMPOTENCY_CONFLICT", 409), ("TASK_EXPIRED", 410), ("TASK_BUDGET_EXHAUSTED", 409), ("REPAIR_LIMIT", 409)])
def test_public_task_error_mapping(code, status):
    from backend.agent.tasks.contracts import task_error
    from backend.domain.errors import ApplicationError
    error = task_error(code)
    assert isinstance(error, ApplicationError)
    assert (error.code, error.status_code, error.retryable) == (code, status, False)


def test_public_task_errors_are_preserved_in_run_diagnostics():
    from backend.agent.persistence import ERROR_CODES, safe_payload
    codes = {"TASK_NOT_FOUND", "TASK_VERSION_CONFLICT", "IDEMPOTENCY_CONFLICT",
             "TASK_EXPIRED", "TASK_BUDGET_EXHAUSTED", "REPAIR_LIMIT"}
    assert codes <= ERROR_CODES
    for code in codes:
        assert safe_payload({"error_code": code}) == {"error_code": code}


@pytest.mark.parametrize("domains", ["diet", set(), None, [None], [[]]])
def test_repair_round_rejects_invalid_domain_collections(domains):
    from backend.agent.tasks.contracts import start_repair_round
    with pytest.raises(ValueError):
        start_repair_round(None, "r", domains)
