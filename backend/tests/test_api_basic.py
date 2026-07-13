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
    assert "today_calories" in dashboard.json()["data"]


def test_deterministic_generation_works_without_model_but_eval_requires_one():
    report = client.post("/report/weekly")
    plan = client.post("/plan/generate")
    eval_result = client.post("/eval/run", json={"limit": 3})

    assert report.json()["success"] is True
    assert report.json()["processing_mode"] == "deterministic"
    assert plan.json()["success"] is True
    assert plan.json()["processing_mode"] == "deterministic"
    assert eval_result.status_code == 409
    assert eval_result.json()["error"]["code"] == "AI_NOT_CONFIGURED"
