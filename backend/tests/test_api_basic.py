from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_health_endpoint_uses_standard_envelope():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"success": True, "data": {"status": "ok"}, "message": ""}


def test_profile_and_dashboard_endpoints_return_data():
    profile = client.get("/profile")
    dashboard = client.get("/dashboard/summary")

    assert profile.status_code == 200
    assert profile.json()["success"] is True
    assert dashboard.status_code == 200
    assert dashboard.json()["success"] is True
    assert dashboard.json()["processing_mode"] == "deterministic"
    assert "today_calories" in dashboard.json()["data"]


def test_deterministic_generation_and_unconfigured_live_eval_cases(tmp_path):
    import json
    from backend import evaluation

    report = client.post("/report/weekly")
    plan = client.post("/plan/generate")
    eval_result = client.post("/eval/run", json={"limit": 3})

    assert report.json()["success"] is True
    assert report.json()["processing_mode"] == "deterministic"
    assert plan.json()["success"] is True
    assert plan.json()["processing_mode"] == "deterministic"
    assert eval_result.status_code == 200
    result = eval_result.json()["data"]
    assert result["execution_mode"] == "live"
    assert result["total_tests"] == 3
    assert len({case["run_id"] for case in result["cases"]}) == 3
    runtime = evaluation.factory.get_agent_runtime()
    for case in result["cases"]:
        assert case["case_status"] == "error"
        assert case["error_code"] == "AI_NOT_CONFIGURED"
        assert case["execution_mode"] == "live"
        assert case["provenance_status"] == "available"
        snapshot = runtime.repository.get(case["run_id"], None)
        assert snapshot.status == "failed"
        assert snapshot.request_id == case["request_id"]
        assert case["policy_version"] == snapshot.policy_version
        assert case["provider"] is snapshot.provider is None
        assert case["model"] is snapshot.model is None
    artifact = evaluation.data_path("eval_results.json")
    assert artifact.parent == tmp_path
    assert json.loads(artifact.read_text(encoding="utf-8")) == result
    assert (tmp_path / "eval_runs" / result["run_id"] / "eval_results.json").exists()
