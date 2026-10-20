"""Coach replay must observe actual async publication, never resend a POST."""
import time

import pytest
from pydantic import ValidationError

from backend.task_evaluation.contracts import Scenario, Step, Suite
from backend.task_evaluation.runner import execute_scenario, _observe_response, CaseError


@pytest.mark.parametrize("method,path", [("POST", "/api/v1/coach/turns/t1"), ("GET", "/chat"), ("GET", "/api/v1/coach/turns/t1/cancel")])
def test_wait_is_only_allowed_on_readonly_turn_status(method, path):
    with pytest.raises(ValidationError):
        Step(method=method, path=path, wait_for_turn=True)


def test_wait_polls_get_without_resending_and_captures_only_final_status():
    class Response:
        status_code = 200
        headers = {"content-type": "application/json"}
        def __init__(self, status): self.status = status
        def json(self): return {"data": {"status": self.status}}

    class Client:
        def __init__(self): self.calls = []
        def request(self, method, path, **kwargs):
            self.calls.append(method)
            return Response("running" if len(self.calls) == 1 else "succeeded")

    client = Client()
    scenario = Scenario(id="wait", version=1, steps=[Step(method="GET", path="/api/v1/coach/turns/t1", wait_for_turn=True,
        observe={"terminal": "data.status"})], expected={"terminal": "succeeded"})
    result = execute_scenario(scenario, client, headers_factory=lambda _: {})
    assert result.status == "passed"
    assert client.calls == ["GET", "GET"]


def test_coach_observation_never_copies_body_or_arbitrary_error_text():
    payload = {"data": {"status": "succeeded", "answer_markdown": "private health text"}}
    assert _observe_response(payload, {"state": "data.status"}) == {"state": "succeeded"}
    with pytest.raises(CaseError):
        _observe_response(payload, {"text": "data.answer_markdown"})


@pytest.mark.parametrize("state,expected,calls", [("running", "failed", 101), ("made-up", "case_error", 1)])
def test_wait_is_bounded_and_unknown_states_never_count_as_completed(monkeypatch, state, expected, calls):
    from types import SimpleNamespace
    import backend.task_evaluation.runner as runner
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    requests = []
    class Client:
        def request(self, method, path, **kwargs):
            requests.append(method)
            return SimpleNamespace(status_code=200, headers={"content-type": "application/json"}, json=lambda: {"data": {"status": state}})
    scenario = Scenario(id="bounded", version=1, steps=[Step(method="GET", path="/api/v1/coach/turns/t1", wait_for_turn=True)])
    result = execute_scenario(scenario, Client(), headers_factory=lambda _: {})
    assert result.status == expected
    assert len(requests) == calls
    assert result.metrics["processing_ms"] > 0


def test_report_only_includes_allowlisted_nonnegative_coach_counts():
    from backend.task_evaluation.runner import CaseResult, to_run_record
    result = CaseResult("safe", 1, "passed", observed={"coach_messages": 2, "body": "private", "coach_turns": "private"})
    record = to_run_record(result, mode="mock")
    assert record.details["coach_invariants"] == {"coach_messages": 2}
    assert "private" not in str(record.details)


def test_final_permitted_poll_can_still_complete(monkeypatch):
    from types import SimpleNamespace
    import backend.task_evaluation.runner as runner
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    requests = []
    class Client:
        def request(self, method, path, **kwargs):
            requests.append(method)
            status = "succeeded" if len(requests) == 101 else "running"
            return SimpleNamespace(status_code=200, headers={"content-type": "application/json"}, json=lambda: {"data": {"status": status}})
    scenario = Scenario(id="last-poll", version=1, steps=[Step(method="GET", path="/api/v1/coach/turns/t1", wait_for_turn=True,
        observe={"terminal": "data.status"})], expected={"terminal": "succeeded"})
    assert execute_scenario(scenario, Client(), headers_factory=lambda _: {}).status == "passed"
    assert len(requests) == 101


def test_boundary_counter_validates_actual_body_not_just_language_receipt(tmp_path):
    import json
    import sqlite3
    from backend.domain.coach_answer import message_catalog
    from backend.task_evaluation.observation import observe_database
    database = tmp_path / 'synthetic.sqlite3'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE coach_messages(turn_id TEXT, user_id TEXT, role TEXT, review_status TEXT, body TEXT)')
        connection.execute('CREATE TABLE coach_turns(turn_id TEXT, user_id TEXT, status TEXT, receipt_json TEXT)')
        connection.execute('INSERT INTO coach_turns VALUES(?,?,?,?)', ('t', 'owner', 'succeeded', json.dumps({'context': {'language': 'en-US'}})))
        connection.execute('INSERT INTO coach_messages VALUES(?,?,?,?,?)', ('t', 'owner', 'coach', 'approved', message_catalog('zh-CN').out_of_scope))
    observed = observe_database(database, actors={'primary': 'owner'})
    assert observed['coach_boundary_replies'] == 0
    assert message_catalog('zh-CN').out_of_scope not in str(observed)
    with sqlite3.connect(database) as connection:
        connection.execute('UPDATE coach_messages SET body=?', (message_catalog('en-US').out_of_scope,))
    assert observe_database(database, actors={'primary': 'owner'})['coach_boundary_replies'] == 1


def test_declared_zero_call_scenarios_require_exactly_zero_model_calls():
    from pathlib import Path
    from backend.task_evaluation.scorers import score_state
    suite = Suite.model_validate_json((Path(__file__).parents[2] / 'task_evaluation/scenarios/coach_conversations.json').read_text(encoding='utf-8'))
    refusal_only = {"coach-zh-boundary", "coach-en-explicit-boundary",
                    "coach-idempotent-owner-isolation", "coach-missing-saved-plan-no-generation"}
    assert refusal_only.issubset({scenario.id for scenario in suite.scenarios})
    for scenario in suite.scenarios:
        if scenario.id in refusal_only:
            assert scenario.expected['gateway_attempts'] == 0
            mutated = {**scenario.expected, 'gateway_attempts': 1}
            assert not score_state(scenario.expected, mutated).passed
        else:
            # A model-backed scenario must not smuggle in a zero-call claim.
            assert scenario.expected.get('gateway_attempts', 1) > 0


@pytest.mark.parametrize("scenario_id", ["coach-zh-boundary", "coach-zh-quick-explain", "coach-stop-cleanup"])
def test_declared_coach_suite_runs_in_network_blocked_isolated_workers(scenario_id):
    from pathlib import Path
    from backend.task_evaluation.runner import run_isolated_scenario
    from backend.task_evaluation.scorers import score_state
    suite = Suite.model_validate_json((Path(__file__).parents[2] / "task_evaluation/scenarios/coach_conversations.json").read_text(encoding="utf-8"))
    scenario = next(item for item in suite.scenarios if item.id == scenario_id)
    result = run_isolated_scenario(scenario, deadline=time.monotonic() + 60)
    assert result.status == "passed", result
    assert score_state(scenario.expected, result.observed).passed, result.observed
    assert result.observed["confirmed_meals"] == 0


def test_only_a_message_count_can_be_observed_from_a_transcript():
    payload = {"data": {"messages": [{"body": "private health text"}]}}
    assert _observe_response(payload, {"count": "data.messages.length"}) == {"count": 1}
    with pytest.raises(CaseError):
        _observe_response(payload, {"body": "data.messages.0.body"})


def test_replay_faults_are_bounded_and_unknown_fields_are_rejected():
    from backend.task_evaluation.contracts import FaultSeeds
    seeds = FaultSeeds(slow_coach_answer_seconds=2, oversize_coach_answer=True, expire_coach_messages_at_step=4)
    assert seeds.slow_coach_answer_seconds == 2
    assert seeds.expire_coach_messages_at_step == 4
    with pytest.raises(ValidationError):
        FaultSeeds(oversize_coach_answer=True, arbitrary_field=True)
    with pytest.raises(ValidationError):
        FaultSeeds(slow_coach_answer_seconds=11)
    with pytest.raises(ValidationError):
        FaultSeeds(expire_coach_messages_at_step=-1)


def test_observation_counts_terminal_states_and_sources_without_bodies(tmp_path):
    import json
    import sqlite3
    from backend.task_evaluation.observation import observe_database
    database = tmp_path / 'synthetic.sqlite3'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE coach_messages(turn_id TEXT, user_id TEXT, role TEXT, review_status TEXT, body TEXT)')
        connection.execute('CREATE TABLE coach_turns(turn_id TEXT, user_id TEXT, status TEXT, receipt_json TEXT)')
        connection.execute('INSERT INTO coach_turns VALUES(?,?,?,?)', ('t1', 'owner', 'cancelled', json.dumps({'sources': [{'source': 'synthetic'}], 'context': {'language': 'zh-CN'}})))
        connection.execute('INSERT INTO coach_turns VALUES(?,?,?,?)', ('t2', 'owner', 'running', '{}'))
        connection.execute('INSERT INTO coach_messages VALUES(?,?,?,?,?)', ('t1', 'owner', 'coach', 'approved', 'private health text'))
    observed = observe_database(database, actors={'primary': 'owner'})
    assert observed['coach_cancelled'] == 1
    assert observed['coach_slot_holders'] == 1
    assert observed['coach_messages_with_sources'] == 1
    assert 'private health text' not in str(observed)
