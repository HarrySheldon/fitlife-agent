from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from backend.domain.model_connection import ModelConnection
from backend.domain.model_connection_setup import ModelConnectionInput
from backend.domain.model_endpoint_policy import ModelEndpointPolicy
from backend.infrastructure.agent_runtime.rate_limiter import ProcessRateLimiter
from backend.infrastructure.settings.fernet_cipher import FernetCredentialCipher
from backend.infrastructure.settings.file_model_connection_repository import FileModelConnectionRepository
from backend.infrastructure.settings.model_verification import SignedModelVerification


@pytest.fixture
def setup_connection(tmp_path):
    from backend.application.use_cases.model_connection_preview import ModelConnectionPreview

    key = Fernet.generate_key().decode()
    cipher = FernetCredentialCipher(key)
    repo = FileModelConnectionRepository(tmp_path)
    repo.save("a", ModelConnection(model="old", enabled=True, encrypted_api_key=cipher.encrypt("old-key")))
    calls = []
    class Gateway:
        def probe_generation(self):
            calls.append("generation")
        def probe_structured(self):
            calls.append("structured")
        def close(self):
            calls.append("closed")
        def list_models(self):
            calls.append("models")
            return ["candidate"]
    gateway = Gateway()
    def factory(connection, credential):
        calls.append((connection.model, credential))
        return gateway
    policy = ModelEndpointPolicy(resolver=lambda *_args, **_kwargs: [(None, None, None, None, ("8.8.8.8", 443))])
    verifier = SignedModelVerification(key)
    service = ModelConnectionPreview(repo, cipher, verifier, factory, policy, ProcessRateLimiter())
    payload = ModelConnectionInput(provider_id="custom", protocol="chat_completions",
        base_url="https://models.example.com/v1", model="candidate", credential_mode="new",
        api_key="synthetic-key", expected_revision=1)
    return SimpleNamespace(repo=repo, service=service, calls=calls, payload=payload,
        gateway=gateway, verifier=verifier, cipher=cipher, path=tmp_path / "users/a/model_connection.json")


def test_preview_tests_current_form_without_writing(setup_connection):
    context = setup_connection
    before = context.path.read_bytes()
    result = context.service.test("a", context.payload)
    assert result["generation"]["status"] == "passed"
    assert result["structured"]["status"] == "passed"
    assert result["verification_token"]
    assert result["status"] == "success"
    assert "tool" not in result
    assert context.calls == [("candidate", "synthetic-key"), "generation", "structured", "closed"]
    assert context.path.read_bytes() == before


@pytest.mark.parametrize("stage", ["generation", "structured"])
def test_probe_failure_has_no_receipt_no_write_and_releases_resources(setup_connection, monkeypatch, stage):
    context = setup_connection
    def fail():
        context.calls.append(stage)
        raise TimeoutError("synthetic-key must not appear in responses")
    monkeypatch.setattr(context.gateway, "probe_" + stage, fail)
    before = context.path.read_bytes()
    result = context.service.test("a", context.payload)
    assert result[stage]["status"] == "failed"
    assert result["status"] == "failed"
    assert result["verification_token"] is None
    assert "synthetic-key" not in str(result)
    assert context.path.read_bytes() == before
    assert context.calls[-1] == "closed"
    if stage == "generation":
        assert result["structured"]["status"] == "not_run"
    # A failed request must release the concurrency lease.
    context.service.list_models("a", context.payload)


def test_reuse_credential_requires_explicit_confirmation_for_new_destination(setup_connection):
    from backend.domain.errors import ApplicationError
    context = setup_connection
    payload = context.payload.model_copy(update={"credential_mode": "reuse_active", "api_key": None})
    with pytest.raises(ApplicationError) as rejected:
        context.service.test("a", payload)
    assert rejected.value.code == "MODEL_CREDENTIAL_REUSE_CONFIRMATION_REQUIRED"
    assert context.calls == []
    context.service.test("a", payload.model_copy(update={"confirm_credential_reuse": True}))
    assert context.calls[0] == ("candidate", "old-key")


def test_models_and_tests_share_rate_limit(setup_connection):
    from backend.domain.errors import ApplicationError
    context = setup_connection
    for _ in range(3):
        context.service.list_models("a", context.payload)
        context.service.test("a", context.payload)
    before_calls = len(context.calls)
    with pytest.raises(ApplicationError) as rejected:
        context.service.test("a", context.payload)
    assert rejected.value.status_code == 429
    assert len(context.calls) == before_calls


def test_list_limit_and_unknown_probe_usage(setup_connection, monkeypatch):
    context = setup_connection
    monkeypatch.setattr(context.gateway, "list_models", lambda: [f"model-{i}" for i in range(220)] + ["x" * 201])
    result = context.service.list_models("a", context.payload)
    assert len(result["models"]) == 200
    assert result["truncated"]
    probe = context.service.test("a", context.payload)
    assert probe["generation"]["usage"] is None
    assert probe["structured"]["usage"] is None


def test_shared_deadline_stops_second_call(setup_connection, monkeypatch):
    context = setup_connection
    clock = [0.0]
    context.service.clock = lambda: clock[0]
    def slow_generation():
        context.calls.append("generation")
        clock[0] = 31
    monkeypatch.setattr(context.gateway, "probe_generation", slow_generation)
    result = context.service.test("a", context.payload)
    assert result["generation"]["error_code"] == "MODEL_TIMEOUT"
    assert result["structured"]["status"] == "not_run"
    assert "structured" not in context.calls


def test_model_discovery_not_supported_is_distinct_from_auth_failure(setup_connection, monkeypatch):
    from backend.domain.errors import ApplicationError
    class Unsupported(Exception):
        status_code = 404
    def fail():
        raise Unsupported("provider secret body")
    monkeypatch.setattr(setup_connection.gateway, "list_models", fail)
    with pytest.raises(ApplicationError) as rejected:
        setup_connection.service.list_models("a", setup_connection.payload)
    assert rejected.value.code == "MODEL_LIST_UNAVAILABLE"
    assert "provider secret body" not in rejected.value.message


def test_typed_authentication_failure_is_preserved_across_probe_boundary(setup_connection, monkeypatch):
    from backend.domain.errors import ApplicationError
    def fail():
        raise ApplicationError(code="MODEL_AUTH_FAILED", message="sanitized", status_code=502)
    monkeypatch.setattr(setup_connection.gateway, "probe_generation", fail)
    result = setup_connection.service.test("a", setup_connection.payload)
    assert result["generation"]["error_code"] == "MODEL_AUTH_FAILED"
    assert result["structured"]["status"] == "not_run"
