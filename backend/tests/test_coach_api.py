from fastapi.testclient import TestClient

from backend.agent import graph as agent_graph
from backend.agent.planner import PlannerRoute
from backend.main import app


client = TestClient(app)


class FakeGateway:
    model = "test-model"

    def plan_route(self, question: str) -> PlannerRoute:
        return PlannerRoute(intent="meal_analysis", needs_meal_analysis=True)

    def write_answer(self, state: dict) -> str:
        return "## Personalized today interpretation\nPrioritize the largest remaining gap."


def test_coach_action_returns_model_answer_with_context(monkeypatch):
    monkeypatch.setattr(agent_graph, "build_model_gateway", lambda: FakeGateway())

    response = client.post(
        "/coach/action",
        json={"surface": "today", "action": "explain_today", "date": "2026-07-09"},
    )

    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    assert body["processing_mode"] == "agent"
    assert data["surface"] == "today"
    assert data["action"] == "explain_today"
    assert data["answer_markdown"].startswith("## Personalized today interpretation")
    assert data["model"] == "test-model"
    assert data["request_id"]
    assert data["trace"]["surface"] == "today"
