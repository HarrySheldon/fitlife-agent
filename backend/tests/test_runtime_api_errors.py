import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.domain.model_connection import ModelConnection
from backend.infrastructure.model_gateway import factory
from backend.infrastructure.model_gateway.openai_responses import build_model_gateway
from backend.main import create_app


def test_unknown_api_exception_is_redacted_and_has_request_id():
    app = create_app()
    @app.get("/_test/unknown")
    def unknown():
        raise RuntimeError("database=/secret/path SQL SELECT prompt=private")

    response = TestClient(app, raise_server_exceptions=False).get("/_test/unknown")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert "secret" not in response.text
    assert "SELECT" not in response.text


def test_openai_client_constructors_disable_sdk_retries(monkeypatch):
    calls = []
    class OpenAI:
        def __init__(self, **kwargs):
            calls.append(kwargs)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=OpenAI))
    settings = SimpleNamespace(llm_enabled=True, openai_api_key="key", openai_base_url=None, openai_model="model")

    build_model_gateway(settings=settings)
    factory.create_model_gateway(ModelConnection(protocol="chat_completions", model="model"), "key")

    assert [call["max_retries"] for call in calls] == [0, 0]
