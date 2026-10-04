import json
import pytest

from backend import evaluation
from backend.evaluation import run_evaluation
from backend.schemas import EvalCase


def test_evaluation_enforces_case_cap_before_starting_any_case(monkeypatch):
    from backend.agent.runtime import AgentRuntime, BudgetExceeded
    from backend.configuration.resolver import ConfigurationResolver
    from backend.infrastructure.agent_runtime import factory
    runtime = AgentRuntime(resolver=ConfigurationResolver(environment={"evaluation": {"max_cases": 1}}))
    monkeypatch.setattr(factory, "get_agent_runtime", lambda: runtime)
    monkeypatch.setattr(evaluation, "read_eval_cases", lambda: [EvalCase(question="one"), EvalCase(question="two")])
    calls = []
    monkeypatch.setattr(evaluation, "run_fitlife_agent", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(BudgetExceeded):
        run_evaluation(user_id="owner")
    assert calls == []


def test_evaluation_passes_authenticated_owner_to_each_case(monkeypatch):
    seen = []
    def fake_agent(question, **kwargs):
        seen.append(kwargs["user_id"])
        return {"answer_markdown": "## Safe answer", "trace": {}}
    monkeypatch.setattr(evaluation, "run_fitlife_agent", fake_agent)
    run_evaluation(limit=2, user_id="owner")
    assert seen == ["owner", "owner"]


def test_eval_api_forwards_authenticated_identity(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import eval as eval_api
    from backend.api.dependencies import optional_current_user
    from backend.schemas import AuthenticatedUser
    seen = {}
    def fake_evaluation(**kwargs):
        seen.update(kwargs)
        return {"total_tests": 0}
    monkeypatch.setattr(eval_api, "run_evaluation", fake_evaluation)
    app = FastAPI()
    app.include_router(eval_api.router)
    app.dependency_overrides[optional_current_user] = lambda: AuthenticatedUser(user_id="owner", display_name="Owner")
    response = TestClient(app).post("/eval/run", json={"limit": 1})
    assert response.status_code == 200
    assert seen["user_id"] == "owner"
    assert seen["request_id"]


def test_evaluation_batch_rate_limit_prevents_case_execution(monkeypatch):
    from backend.agent.runtime import AgentRuntime
    from backend.configuration.resolver import ConfigurationResolver
    from backend.infrastructure.agent_runtime import factory
    from backend.infrastructure.agent_runtime.rate_limiter import RateLimitExceeded
    runtime = AgentRuntime(resolver=ConfigurationResolver(environment={"rate_limit": {"requests_per_minute": 1}}))
    monkeypatch.setattr(factory, "get_agent_runtime", lambda: runtime)
    monkeypatch.setattr(evaluation, "read_eval_cases", lambda: [])
    run_evaluation(user_id="owner")
    with pytest.raises(RateLimitExceeded):
        run_evaluation(user_id="owner")


def test_run_evaluation_returns_metrics_and_cases(monkeypatch):
    monkeypatch.setattr(
        evaluation,
        "run_fitlife_agent",
        lambda question, **kwargs: {
            "answer_markdown": "## Model answer",
            "trace": {
                "tool_calls": [],
                "retrieved_sources": [],
                "validation_passed": True,
            },
        },
    )

    result = run_evaluation(limit=3)

    assert result["total_tests"] == 3
    assert 0 <= result["pass_rate"] <= 1
    assert "tool_call_success_rate" in result
    assert "cases" in result


def test_run_evaluation_returns_structured_checks_and_failure_reasons(monkeypatch):
    cases = [
        EvalCase(
            question="passing case",
            expected_tool="analyze_meals",
            expected_answer_format="markdown",
            expected_keywords=["protein"],
        ),
        EvalCase(
            question="failing case",
            expected_tool="retrieve_knowledge",
            expected_retrieval_doc="fitness_rules.md",
            expected_answer_format="markdown",
            expected_keywords=["rest"],
        ),
    ]

    def fake_agent(question: str, **kwargs) -> dict:
        if question == "passing case":
            return {
                "answer_markdown": "## Summary\nprotein target was reached",
                "trace": {
                    "tool_calls": ["analyze_meals"],
                    "retrieved_sources": [],
                    "validation_passed": True,
                },
            }
        return {
            "answer_markdown": "plain answer without expected content",
            "trace": {
                "tool_calls": ["analyze_meals"],
                "retrieved_sources": ["meal_templates.md"],
                "validation_passed": False,
            },
        }

    monkeypatch.setattr(evaluation, "read_eval_cases", lambda: cases)
    monkeypatch.setattr(evaluation, "run_fitlife_agent", fake_agent)

    result = run_evaluation()

    passing_case = result["cases"][0]
    assert passing_case["passed"] is True
    assert passing_case["failure_reasons"] == []
    assert {check["name"] for check in passing_case["checks"]} == {
        "tool_call",
        "retrieval",
        "keywords",
        "answer_format",
        "validator",
    }
    assert all(set(check) == {"name", "passed", "reason"} for check in passing_case["checks"])

    failing_case = result["cases"][1]
    assert failing_case["passed"] is False
    assert len(failing_case["failure_reasons"]) == 5
    assert failing_case["case_status"] == "failed"
    assert failing_case["question"] == "Case 2" and "trace" not in failing_case
    assert any("validator" in reason.lower() for reason in failing_case["failure_reasons"])


def test_run_evaluation_returns_group_metrics_and_writes_artifacts(monkeypatch):
    cases = [
        EvalCase(
            question="meal case",
            expected_tool="analyze_meals",
            expected_answer_format="markdown",
            expected_keywords=["protein"],
        ),
        EvalCase(
            question="knowledge case",
            expected_tool="retrieve_knowledge",
            expected_retrieval_doc="meal_templates.md",
            expected_answer_format="markdown",
            expected_keywords=["replacement"],
        ),
    ]

    def fake_agent(question: str, **kwargs) -> dict:
        return {
            "answer_markdown": "## Answer\nprotein replacement",
            "trace": {
                "tool_calls": ["analyze_meals", "retrieve_knowledge"],
                "retrieved_sources": ["meal_templates.md"],
                "validation_passed": True,
            },
        }

    monkeypatch.setattr(evaluation, "read_eval_cases", lambda: cases)
    monkeypatch.setattr(evaluation, "run_fitlife_agent", fake_agent)

    result = run_evaluation()

    assert result["group_metrics"]["by_expected_tool"]["analyze_meals"] == {"total": 1, "pass_rate": 1.0}
    assert result["group_metrics"]["by_expected_tool"]["retrieve_knowledge"] == {"total": 1, "pass_rate": 1.0}
    assert result["group_metrics"]["by_retrieval_requirement"]["requires_retrieval"] == {"total": 1, "pass_rate": 1.0}
    assert result["group_metrics"]["by_retrieval_requirement"]["no_retrieval_expected"] == {
        "total": 1,
        "pass_rate": 1.0,
    }

    json_artifact = evaluation.data_path("eval_results.json")
    markdown_artifact = evaluation.data_path("eval_results.md")

    saved = json.loads(json_artifact.read_text(encoding="utf-8"))
    assert saved["group_metrics"] == result["group_metrics"]
    assert "# FitLife Agent Evaluation" in markdown_artifact.read_text(encoding="utf-8")


def test_case_requests_are_unique_and_linked_to_the_batch(monkeypatch):
    requests = []

    def fake_agent(question, **kwargs):
        requests.append(kwargs["request_id"])
        return {"answer_markdown": "## Answer", "trace": {}, "request_id": kwargs["request_id"]}

    monkeypatch.setattr(evaluation, "run_fitlife_agent", fake_agent)
    result = run_evaluation(limit=3, request_id="batch-request")
    assert len(requests) == len(set(requests)) == 3
    assert all(request and request != "batch-request" for request in requests)
    assert result["request_id"] == "batch-request"
    assert [case["request_id"] for case in result["cases"]] == requests
    assert all(case["batch_request_id"] == "batch-request" for case in result["cases"])


def test_case_errors_continue_and_reports_are_safe(monkeypatch):
    from backend.agent.runtime import RunTimedOut
    monkeypatch.setattr(evaluation, "read_eval_cases", lambda: [EvalCase(question=f"private health {i}") for i in range(3)])
    answers = iter([RuntimeError("secret provider body"), RunTimedOut("private timeout"), {"answer_markdown": "## private answer", "trace": {"secret": "private trace"}}])
    def fake_agent(*args, **kwargs):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(evaluation, "run_fitlife_agent", fake_agent)
    report = run_evaluation(execution_mode="mock")
    assert [case["case_status"] for case in report["cases"]] == ["error", "timed_out", "passed"]
    assert report["execution_mode"] == "mock"
    assert report["dataset_hash"] and report["run_id"]
    saved = evaluation.data_path("eval_results.json").read_text(encoding="utf-8")
    assert "private" not in saved and "secret" not in saved


def test_batch_budget_reserves_case_maxima_and_skips_remaining(monkeypatch):
    from backend.agent.runtime import AgentRuntime
    from backend.configuration.resolver import ConfigurationResolver
    runtime = AgentRuntime(resolver=ConfigurationResolver(environment={"evaluation": {"max_model_calls": 16}}))
    monkeypatch.setattr(evaluation.factory, "get_agent_runtime", lambda: runtime)
    monkeypatch.setattr(evaluation, "read_eval_cases", lambda: [EvalCase(question="protein") for _ in range(3)])
    calls = []
    def fake_agent(*args, **kwargs):
        calls.append(args)
        return {"answer_markdown": "## Answer", "trace": {}}
    monkeypatch.setattr(evaluation, "run_fitlife_agent", fake_agent)
    report = run_evaluation(execution_mode="mock")
    assert len(calls) == 1
    assert [case["case_status"] for case in report["cases"]] == ["passed", "skipped", "skipped"]


def test_preflight_validates_excluded_cases_and_storage(monkeypatch):
    monkeypatch.setattr(evaluation, "read_eval_cases", lambda: [{"question": "valid"}, {"question": "invalid", "unknown": True}])
    with pytest.raises(ValueError):
        run_evaluation(limit=1, execution_mode="mock")
    monkeypatch.setattr(evaluation, "read_eval_cases", lambda: [EvalCase(question="valid")])
    monkeypatch.setattr(evaluation, "_preflight_artifacts", lambda: (_ for _ in ()).throw(OSError("storage unavailable")))
    monkeypatch.setattr(evaluation, "run_fitlife_agent", lambda *a, **k: pytest.fail("case started"))
    with pytest.raises(OSError):
        run_evaluation(execution_mode="mock")


def test_scoring_failure_isolated_to_case(monkeypatch):
    monkeypatch.setattr(evaluation, "read_eval_cases", lambda: [EvalCase(question="one"), EvalCase(question="two")])
    monkeypatch.setattr(evaluation, "run_fitlife_agent", lambda *a, **k: {"answer_markdown": "## Answer", "trace": {}})
    original = evaluation._build_case_checks
    def scorer(case, trace, answer):
        if case.question == "one":
            raise RuntimeError("private scorer details")
        return original(case, trace, answer)
    monkeypatch.setattr(evaluation, "_build_case_checks", scorer)
    report = run_evaluation(execution_mode="mock")
    assert [case["case_status"] for case in report["cases"]] == ["error", "passed"]
    assert "private" not in json.dumps(report)


def test_mock_uses_runtime_and_actual_snapshot_without_live_selection(monkeypatch):
    from backend.agent import graph
    monkeypatch.setattr(graph, "_resolve_gateway", lambda *a: pytest.fail("live selection in mock"))
    monkeypatch.setattr(evaluation, "read_eval_cases", lambda: [EvalCase(question="How can I eat more protein?")])
    report = run_evaluation(execution_mode="mock")
    case = report["cases"][0]
    runtime = evaluation.factory.get_agent_runtime()
    snapshot = runtime.repository.get(case["run_id"], None)
    assert snapshot.status == "succeeded"
    assert case["policy_version"] == snapshot.policy_version
    assert case["provider"] == snapshot.provider == "mock"
    assert case["model"] == snapshot.model == "deterministic-eval-v1"
    assert case["started_at"] == snapshot.started_at
    assert case["finished_at"] == snapshot.finished_at
    assert (evaluation.data_path("eval_runs") / report["run_id"] / "eval_results.json").exists()


def test_live_selection_failure_has_independent_run_records(monkeypatch):
    from backend.agent import graph
    monkeypatch.setattr(evaluation, "read_eval_cases", lambda: [EvalCase(question="one"), EvalCase(question="two")])
    def unavailable(*args):
        raise RuntimeError("private credential detail")
    monkeypatch.setattr(graph, "_resolve_gateway", unavailable)
    report = run_evaluation()
    assert [case["case_status"] for case in report["cases"]] == ["error", "error"]
    assert len({case["run_id"] for case in report["cases"]}) == 2
    assert all(case["run_id"] and case["policy_version"] for case in report["cases"])
    assert "private" not in json.dumps(report)


def test_live_selection_is_bounded_by_each_runtime_deadline(monkeypatch):
    import time
    from backend.agent import graph
    from backend.agent.runtime import AgentRuntime
    from backend.configuration.resolver import ConfigurationResolver
    runtime = AgentRuntime(resolver=ConfigurationResolver(environment={"deadline_seconds": 0.03}))
    monkeypatch.setattr(evaluation.factory, "get_agent_runtime", lambda: runtime)
    monkeypatch.setattr(evaluation, "read_eval_cases", lambda: [EvalCase(question="one"), EvalCase(question="two")])
    monkeypatch.setattr(graph, "get_fitness_repository", lambda: object())
    def slow_selection(*args):
        time.sleep(0.15)
        raise RuntimeError("private provider selection")
    monkeypatch.setattr(graph, "_resolve_gateway", slow_selection)
    report = run_evaluation()
    assert [case["case_status"] for case in report["cases"]] == ["timed_out", "timed_out"]
    assert all(runtime.repository.get(case["run_id"], None).status == "timed_out" for case in report["cases"])


def test_token_reservation_skips_rest_and_batch_artifacts_are_unique(monkeypatch):
    from backend.agent.runtime import AgentRuntime
    from backend.configuration.resolver import ConfigurationResolver
    runtime = AgentRuntime(resolver=ConfigurationResolver(environment={"evaluation": {"max_tokens": 32000}}))
    monkeypatch.setattr(evaluation.factory, "get_agent_runtime", lambda: runtime)
    monkeypatch.setattr(evaluation, "read_eval_cases", lambda: [EvalCase(question="one"), EvalCase(question="two")])
    monkeypatch.setattr(evaluation, "run_fitlife_agent", lambda *a, **k: {"answer_markdown": "## Answer", "trace": {}})
    first = run_evaluation(execution_mode="mock")
    second = run_evaluation(execution_mode="mock")
    assert first["run_id"] != second["run_id"]
    for report in (first, second):
        assert [case["case_status"] for case in report["cases"]] == ["passed", "skipped"]
        skipped = report["cases"][1]
        assert skipped["run_id"] is skipped["started_at"] is skipped["policy_version"] is None
        assert report["budget"]["reserved_tokens"] == 32000
        artifact = evaluation.data_path("eval_runs") / report["run_id"] / "eval_results.json"
        assert json.loads(artifact.read_text(encoding="utf-8"))["run_id"] == report["run_id"]
    assert json.loads(evaluation.data_path("eval_results.json").read_text(encoding="utf-8"))["run_id"] == second["run_id"]


@pytest.mark.parametrize("dataset", [None, "{}", '""', "null", "42"])
def test_dataset_missing_or_non_list_fails_before_cases_and_preserves_reports(monkeypatch, tmp_path, dataset):
    from backend.tools import data_access
    dataset_path = tmp_path / "eval_questions.json"
    if dataset is not None:
        dataset_path.write_text(dataset, encoding="utf-8")
    monkeypatch.setattr(data_access, "data_path", lambda filename: tmp_path / filename)
    monkeypatch.setattr(evaluation, "read_eval_cases", data_access.read_eval_cases)
    monkeypatch.setattr(evaluation, "run_fitlife_agent", lambda *a, **k: pytest.fail("case launched before dataset validation"))
    for filename in ("eval_results.json", "eval_results.md"):
        (tmp_path / filename).write_text("existing report", encoding="utf-8")
    with pytest.raises((FileNotFoundError, ValueError)):
        run_evaluation(execution_mode="mock")
    assert not (tmp_path / "eval_runs").exists()
    for filename in ("eval_results.json", "eval_results.md"):
        assert (tmp_path / filename).read_text(encoding="utf-8") == "existing report"


def test_explicit_empty_dataset_is_valid(monkeypatch, tmp_path):
    from backend.tools import data_access
    (tmp_path / "eval_questions.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(data_access, "data_path", lambda filename: tmp_path / filename)
    monkeypatch.setattr(evaluation, "read_eval_cases", data_access.read_eval_cases)
    assert run_evaluation(execution_mode="mock")["total_tests"] == 0


def test_repository_create_failure_does_not_abort_remaining_cases(monkeypatch):
    from backend.agent.runtime import AgentRuntime
    from backend.infrastructure.agent_runtime.memory_run_repository import MemoryRunRepository

    class FailingCreateRepository(MemoryRunRepository):
        attempts = 0

        def create(self, run):
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("private storage details")
            return super().create(run)

    repository = FailingCreateRepository()
    runtime = AgentRuntime(repository=repository)
    monkeypatch.setattr(evaluation.factory, "get_agent_runtime", lambda: runtime)
    monkeypatch.setattr(evaluation, "read_eval_cases", lambda: [EvalCase(question="protein", expected_answer_format="text") for _ in range(2)])
    report = run_evaluation(execution_mode="mock")
    first, second = report["cases"]
    assert repository.attempts == 2
    assert first["case_status"] == "error" and first["error_code"] == "INTERNAL_ERROR"
    assert first["provenance_status"] == "unavailable"
    assert first["policy_version"] is first["provider"] is first["model"] is None
    assert second["case_status"] == "passed"
    assert second["provenance_status"] == "available"
    assert repository.get(second["run_id"], None).status == "succeeded"
    assert "private" not in json.dumps(report)
    assert json.loads(evaluation.data_path("eval_results.json").read_text(encoding="utf-8")) == report


def test_snapshot_read_failure_invalidates_score_and_continues(monkeypatch):
    from backend.agent.runtime import AgentRuntime
    from backend.infrastructure.agent_runtime.memory_run_repository import MemoryRunRepository

    class FailingReadRepository(MemoryRunRepository):
        fail_next_read = False

        def get(self, run_id, user_id):
            if self.fail_next_read:
                self.fail_next_read = False
                raise OSError("private storage detail")
            return super().get(run_id, user_id)

    repository = FailingReadRepository()
    runtime = AgentRuntime(repository=repository)
    monkeypatch.setattr(evaluation.factory, "get_agent_runtime", lambda: runtime)
    monkeypatch.setattr(evaluation, "read_eval_cases", lambda: [EvalCase(question="protein", expected_answer_format="text") for _ in range(2)])
    execute = evaluation.run_fitlife_agent
    completed = []

    def execute_then_fail_first_snapshot(*args, **kwargs):
        response = execute(*args, **kwargs)
        if not completed:
            repository.fail_next_read = True
        completed.append(response["run_id"])
        return response

    monkeypatch.setattr(evaluation, "run_fitlife_agent", execute_then_fail_first_snapshot)
    report = run_evaluation(execution_mode="mock")
    first, second = report["cases"]
    assert first["case_status"] == "error" and first["error_code"] == "INTERNAL_ERROR"
    assert first["passed"] is False and first["checks"] == []
    assert all(first[key] is False for key in evaluation._METRICS)
    assert first["provenance_status"] == "unavailable"
    assert first["policy_version"] is first["provider"] is first["model"] is None
    assert repository.get(first["run_id"], None).status == "succeeded"
    assert second["case_status"] == "passed" and second["provenance_status"] == "available"
    assert "private" not in json.dumps(report)
