import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.domain.model_connection import ModelConnection
from backend.infrastructure.model_gateway import factory
from backend.infrastructure.model_gateway.openai_responses import build_model_gateway
from backend.main import create_app
from backend.agent.runtime import BudgetExceeded
from backend.domain.errors import ApplicationError


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


def test_runtime_budget_failure_uses_whitelisted_public_error():
    app = create_app()
    @app.get("/_test/budget")
    def budget():
        raise BudgetExceeded("internal budget details")

    response = TestClient(app, raise_server_exceptions=False).get("/_test/budget")

    assert response.status_code == 429
    assert response.json()["error"] == {
        "code": "RUN_BUDGET_EXCEEDED",
        "message": "The Agent run reached its usage limit.",
        "action": "Reduce the request size or try again later.",
        "retryable": False,
        "retry_after_ms": None,
        "request_id": response.headers["x-request-id"],
    }
    assert "internal budget" not in response.text


def test_final_rate_limit_error_includes_retry_after_ms():
    app = create_app()
    @app.get("/_test/rate-limit")
    def rate_limit():
        raise ApplicationError(code="MODEL_RATE_LIMITED", message="internal", status_code=429,
                               retryable=True, retry_after_ms=2500)

    response = TestClient(app, raise_server_exceptions=False).get("/_test/rate-limit")

    assert response.status_code == 429
    assert response.json()["error"]["retryable"] is True
    assert response.json()["error"]["retry_after_ms"] == 2500


def test_unknown_error_message_is_localized_without_leaking_details():
    app = create_app()
    @app.get("/_test/localized-unknown")
    def unknown():
        raise RuntimeError("secret provider body")

    response = TestClient(app, raise_server_exceptions=False).get(
        "/_test/localized-unknown", headers={"accept-language": "zh-CN"}
    )

    assert response.json()["error"]["message"] == "请求未能完成，请稍后重试。"
    assert "secret" not in response.text
