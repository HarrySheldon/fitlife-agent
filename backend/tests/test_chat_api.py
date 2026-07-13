from fastapi.testclient import TestClient

from backend.agent import graph as agent_graph
from backend.agent.planner import plan_route
from backend.main import app


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


def test_chat_retrieval_question_cites_source(monkeypatch):
    monkeypatch.setattr(agent_graph, "build_model_gateway", lambda: FakeGateway())

    response = client.post("/chat", json={"question": "我不想吃鸡胸肉，有什么替代？"})

    body = response.json()
    assert body["success"] is True
    assert body["data"]["trace"]["retrieved_sources"]
    assert "替代" in body["data"]["answer_markdown"]
