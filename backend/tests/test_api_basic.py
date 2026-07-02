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


def test_report_plan_and_eval_endpoints_smoke():
    report = client.post("/report/weekly")
    plan = client.post("/plan/generate")
    eval_result = client.post("/eval/run", json={"limit": 3})

    assert report.json()["success"] is True
    assert plan.json()["success"] is True
    assert eval_result.json()["success"] is True
