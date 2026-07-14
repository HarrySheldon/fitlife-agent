from fastapi.testclient import TestClient

from backend.agent import graph as agent_graph
from backend.agent.planner import plan_route
from backend.api import dependencies
from backend.main import app
from backend.schemas import AuthenticatedUser


client = TestClient(app)


class FakeGateway:
    model = "test-model"

    def plan_route(self, question: str):
        return plan_route(question)

    def write_answer(self, state: dict) -> str:
        if "鸡胸" in state["user_query"]:
            return "## 替代建议\n可以选择鱼、豆腐或低脂奶制品。"
        return "## 蛋白质分析\n请结合记录查看蛋白质完成情况。"


def test_chat_meal_analysis_returns_agent_metadata(monkeypatch):
    monkeypatch.setattr(agent_graph, "build_model_gateway", lambda: FakeGateway())

    response = client.post("/chat", json={"question": "我这周蛋白质吃够了吗？"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["processing_mode"] == "agent"
    assert body["data"]["model"] == "test-model"
    assert body["data"]["request_id"]
    assert "蛋白质" in body["data"]["answer_markdown"]
    assert "analyze_meals" in body["data"]["trace"]["tool_calls"]


def test_authenticated_chat_uses_user_gateway(monkeypatch):
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
        "/chat",
        headers={"Authorization": "Bearer valid-user-token"},
        json={"question": "How is my protein intake?"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["model"] == "test-model"


def test_chat_retrieval_question_cites_source(monkeypatch):
    monkeypatch.setattr(agent_graph, "build_model_gateway", lambda: FakeGateway())

    response = client.post("/chat", json={"question": "我不想吃鸡胸肉，有什么替代？"})

    body = response.json()
    assert body["success"] is True
    assert body["data"]["trace"]["retrieved_sources"]
    assert "替代" in body["data"]["answer_markdown"]
