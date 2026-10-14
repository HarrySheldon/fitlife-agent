"""Fast tests for controlled workflow classifications without providers."""
from types import SimpleNamespace
import inspect
import pytest
from backend.task_evaluation.contracts import Scenario
from backend.task_evaluation.runner import execute_scenario, CaseError


class FakeClient:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
    def request(self, *args, **kwargs):
        return SimpleNamespace(status_code=self.status, headers={"content-type": "application/json"}, json=lambda: self.payload)


@pytest.mark.parametrize("missing,answers,status", [
    (["amount"], {}, "unexpected_question"),
    ([{"name": "amount"}], {"amount": 100}, "unsupported"),
    ([{"field": "date"}], {"amount": 100}, "unexpected_question"),
])
def test_missing_field_answers_are_matched_by_name_and_multiturn_unsupported(missing, answers, status):
    scenario = Scenario.model_validate({"id": "fields", "version": 1, "steps": [{"method": "POST", "path": "/chat", "answer_by_field": answers}]})
    result = execute_scenario(scenario, FakeClient({"data": {"missing_fields": missing}}), headers_factory=lambda actor: {})
    assert result.status == status
    assert result.metrics["processing_ms"] >= 0


def test_failed_http_keeps_processing_and_final_state():
    scenario = Scenario.model_validate({"id": "failure", "version": 1, "steps": [{"method": "GET", "path": "/today", "expected_status": 200}]})
    result = execute_scenario(scenario, FakeClient({}, 500), headers_factory=lambda actor: {}, observer=lambda: {"confirmed_meals": 0})
    assert result.status == "failed"
    assert result.metrics["processing_ms"] >= 0
    assert result.metrics["candidate_ms"] is None
    assert result.observed == {"confirmed_meals": 0}


def test_intruder_cannot_fall_back_to_primary_factory():
    scenario = Scenario.model_validate({"id": "actor", "version": 1, "steps": [{"actor": "intruder", "method": "GET", "path": "/today"}]})
    with pytest.raises(CaseError):
        execute_scenario(scenario, FakeClient({}), headers_factory=lambda: {"Authorization": "synthetic"})


def test_legacy_evaluation_default_mode_remains_live_without_calling_it():
    from backend.evaluation import run_evaluation
    assert inspect.signature(run_evaluation).parameters["execution_mode"].default == "live"


def test_explicit_falsey_legacy_seed_is_not_silently_ignored():
    from backend.task_evaluation.seeding import seed_environment, UnsupportedSeed
    scenario = Scenario.model_validate({"id": "legacy", "version": 1, "initial_state": {"profile": {"weekly_training_frequency": 0}}})
    class RegistrationClient:
        def request(self, *args, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: {"data": {"access_token": "synthetic", "user": {"user_id": "synthetic"}}})
    with pytest.raises(UnsupportedSeed):
        seed_environment(RegistrationClient(), scenario, None)


def test_spawn_serialization_preserves_profile_declaration_intent():
    scenario = Scenario.model_validate({"id": "roundtrip", "version": 1, "initial_state": {"profile": {"height_cm": 175}}})
    restored = Scenario.model_validate(scenario.model_dump(mode="json", exclude_unset=True))
    assert restored.initial_state.profile.model_fields_set == {"height_cm"}
    assert "diet_preferences" not in restored.initial_state.profile.model_dump(exclude_unset=True)


@pytest.mark.parametrize("valid", [True, False])
def test_first_candidate_ready_survives_new_version_and_confirm(monkeypatch, valid):
    import itertools
    import backend.task_evaluation.runner as runner
    clock = itertools.count()
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(clock))
    candidate = {"id": "c", "kind": "strength", "raw_text": "synthetic", "normalized_text": "synthetic", "subject_text": "synthetic", "meal_context": None, "selected": True, "selected_catalog_id": "exercise", "catalog_choices": [], "issues": [], "values": {"name": "synthetic", "primary_muscle": "legs", "set_count": 3, "reps": 8}, "provenance": {}}
    if not valid:
        candidate["values"].pop("reps")
    payloads = iter([{"data": {"id": "draft", "version": version, "payload": {"candidates": [candidate]}}} for version in (1, 2)] + [{"data": {"draft_id": "draft", "meal_ids": ["synthetic"]}}])
    class Client:
        def request(self, *args, **kwargs):
            payload = next(payloads)
            return SimpleNamespace(status_code=200, headers={"content-type": "application/json"}, json=lambda: payload)
    scenario = Scenario.model_validate({"id": "candidate", "version": 1, "steps": [{"method": "POST", "path": "/api/v1/smart-entry-drafts"}, {"method": "PATCH", "path": "/api/v1/smart-entry-drafts/draft"}, {"method": "POST", "path": "/api/v1/smart-entry-drafts/draft/confirm", "headers": {"If-Match": "2"}}]})
    result = execute_scenario(scenario, Client(), headers_factory=lambda actor: {})
    assert result.metrics["candidate_ms"] == (2000 if valid else None)
    if valid:
        assert result.metrics["first_candidate"]["version"] == 1
        assert result.metrics["confirmed_candidate"]["version"] == 2
    else:
        assert result.metrics["first_candidate"] is None
        assert result.metrics["confirmed_candidate"] is None


def test_exception_metrics_preserve_known_provenance_and_processing(tmp_path):
    from backend.task_evaluation.worker import collect_metrics
    from backend.task_evaluation.budget import MeteredMockGateway, BatchBudget
    fixed = SimpleNamespace(llm_enabled=False, safety_review_mode="off", safety_grounding_mode="legacy")
    gateway = MeteredMockGateway(BatchBudget(2))
    gateway._call(lambda: "synthetic")
    metrics = collect_metrics(tmp_path, fixed, gateway, {"processing_ms": 12})
    assert metrics["processing_ms"] == 12
    assert metrics["model"] == "deterministic-eval-v1"
    assert metrics["rule_version"] and metrics["safe_config_fingerprint"]


def test_invalid_plan_file_is_not_observed_as_valid_plan(tmp_path):
    import sqlite3
    from backend.task_evaluation.observation import observe_database
    database = tmp_path / "fitlife.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE meals(user_id)")
    plans = tmp_path / "users" / "synthetic" / "plans"
    plans.mkdir(parents=True)
    (plans / "plan-12345678.json").write_text('{"invalid":true}', encoding="utf-8")
    observed = observe_database(database, actors={"primary": "synthetic"}, data_dir=tmp_path)
    assert observed["plan_history_count"] == 1
    assert observed["plans_readable"] is False
    assert observed["plans_validated"] is False
