from backend.evaluation import run_evaluation


def test_run_evaluation_returns_metrics_and_cases():
    result = run_evaluation(limit=3)

    assert result["total_tests"] == 3
    assert 0 <= result["pass_rate"] <= 1
    assert "tool_call_success_rate" in result
    assert "cases" in result
