from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_today_overview_returns_daily_state():
    response = client.get("/today?date=2026-07-09")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["processing_mode"] == "deterministic"
    data = payload["data"]
    assert data["date"] == "2026-07-09"
    assert "summary" in data
    assert "meals" in data
    assert "workouts" in data
    assert "targets" in data
    assert "coach_actions" in data
