from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_coach_action_wraps_agent_with_context():
    response = client.post(
        "/coach/action",
        json={"surface": "today", "action": "explain_today", "date": "2026-07-09"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["surface"] == "today"
    assert data["action"] == "explain_today"
    assert data["answer_markdown"]
    assert "Today's status" in data["answer_markdown"]
    assert "2026-07-09" in data["answer_markdown"]
    assert data["trace"]["surface"] == "today"
