from fastapi.testclient import TestClient

from backend.api.utils import ok
from backend.main import app


client = TestClient(app)


def test_ok_can_identify_deterministic_processing():
    response = ok({"value": 1}, processing_mode="deterministic")

    assert response["processing_mode"] == "deterministic"
    assert "error" not in response


def test_agent_without_model_uses_stable_error_contract():
    response = client.post("/chat", json={"question": "Help me understand this week"})

    assert response.status_code == 409
    assert response.json() == {
        "success": False,
        "data": None,
        "message": "Configure and enable a model connection before using Agent features.",
        "processing_mode": "agent",
        "error": {
            "code": "AI_NOT_CONFIGURED",
            "message": "Configure and enable a model connection before using Agent features.",
        },
    }
