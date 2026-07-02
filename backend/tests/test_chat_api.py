from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_chat_meal_analysis_returns_trace_and_markdown():
    response = client.post("/chat", json={"question": "我这周蛋白质吃够了吗？"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "蛋白质" in body["data"]["answer_markdown"]
    assert "analyze_meals" in body["data"]["trace"]["tool_calls"]


def test_chat_retrieval_question_cites_source():
    response = client.post("/chat", json={"question": "我不想吃鸡胸肉，有什么替代？"})

    body = response.json()
    assert body["success"] is True
    assert body["data"]["trace"]["retrieved_sources"]
    assert "替代" in body["data"]["answer_markdown"]
