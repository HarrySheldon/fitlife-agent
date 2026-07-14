from fastapi.testclient import TestClient

from backend.agent import graph as agent_graph
from backend.agent.planner import PlannerRoute
from backend.api import dependencies
from backend.main import app
from backend.schemas import AuthenticatedUser


client = TestClient(app)


class FakeGateway:
    model = "test-model"

    def plan_route(self, question: str) -> PlannerRoute:
        return PlannerRoute(intent="meal_analysis", needs_meal_analysis=True)

    def write_answer(self, state: dict) -> str:
        return "## Personalized today interpretation\nPrioritize the largest remaining gap."


def test_authenticated_coach_uses_user_gateway(monkeypatch):
    monkeypatch.setattr(
        dependencies,
        "user_from_token",
        lambda token: AuthenticatedUser(user_id="user-a", username="user-a", display_name="User A"),
    )
    monkeypatch.setattr(agent_graph, "resolve_user_model_gateway", lambda user_id: FakeGateway())
    monkeypatch.setattr(
        agent_graph,
        "build_model_gateway",
        lambda: (_ for _ in ()).throw(AssertionError("deployment gateway must be ignored")),
    )

    response = client.post(
        "/coach/action",
        headers={"Authorization": "Bearer valid-user-token"},
        json={"surface": "today", "action": "explain_today", "date": "2026-07-09"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["model"] == "test-model"


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
