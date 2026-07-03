import json

from backend import evaluation
from backend.evaluation import run_evaluation
from backend.schemas import EvalCase
from backend.tools.data_access import data_path


def test_run_evaluation_returns_metrics_and_cases():
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

    def fake_agent(question: str) -> dict:
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
    assert all({"name", "passed", "expected", "observed", "reason"}.issubset(check) for check in passing_case["checks"])

    failing_case = result["cases"][1]
    assert failing_case["passed"] is False
    assert any("retrieve_knowledge" in reason for reason in failing_case["failure_reasons"])
    assert any("fitness_rules.md" in reason for reason in failing_case["failure_reasons"])
    assert any("rest" in reason for reason in failing_case["failure_reasons"])
    assert any("markdown" in reason for reason in failing_case["failure_reasons"])
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

    def fake_agent(question: str) -> dict:
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

    json_artifact = data_path("eval_results.json")
    markdown_artifact = data_path("eval_results.md")

    saved = json.loads(json_artifact.read_text(encoding="utf-8"))
    assert saved["group_metrics"] == result["group_metrics"]
    assert "# FitLife Agent Evaluation" in markdown_artifact.read_text(encoding="utf-8")
