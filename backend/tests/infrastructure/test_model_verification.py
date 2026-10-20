import pytest
from cryptography.fernet import Fernet


def test_receipt_is_bound_to_user_configuration_and_expiry():
    from backend.infrastructure.settings.model_verification import SignedModelVerification
    from backend.domain.errors import ApplicationError

    now = [1000.0]
    verifier = SignedModelVerification(Fernet.generate_key().decode(), clock=lambda: now[0])
    binding = {"user_id": "a", "revision": 3, "model": "synthetic",
               "credential_fingerprint": verifier.fingerprint("synthetic-secret")}
    token = verifier.issue(binding)
    verifier.verify(token, binding)
    assert "synthetic-secret" not in token
    for changed in ({**binding, "user_id": "b"}, {**binding, "model": "other"}, {**binding, "revision": 4}):
        with pytest.raises(ApplicationError):
            verifier.verify(token, changed)
    with pytest.raises(ApplicationError):
        verifier.verify(token + "tampered", binding)
    now[0] += 901
    with pytest.raises(ApplicationError):
        verifier.verify(token, binding)


def test_receipt_rejects_future_clock_and_changed_probe_version(monkeypatch):
    from backend.infrastructure.settings.model_verification import SignedModelVerification
    from backend.domain.errors import ApplicationError
    clock = [1000.0]
    verifier = SignedModelVerification(Fernet.generate_key().decode(), clock=lambda: clock[0])
    token = verifier.issue({"user_id": "a"})
    clock[0] = 900
    with pytest.raises(ApplicationError):
        verifier.verify(token, {"user_id": "a"})
    clock[0] = 1000
    monkeypatch.setattr("backend.infrastructure.settings.model_verification.PROBE_VERSION", "v-next")
    with pytest.raises(ApplicationError):
        verifier.verify(token, {"user_id": "a"})


@pytest.mark.parametrize("token", ["", "bad", "x" * 4097, "bad.signature", "💥.signature"])
def test_malformed_receipts_fail_closed(token):
    from backend.infrastructure.settings.model_verification import SignedModelVerification
    from backend.domain.errors import ApplicationError
    verifier = SignedModelVerification(Fernet.generate_key().decode())
    with pytest.raises(ApplicationError):
        verifier.verify(token, {})


def test_large_unicode_configuration_still_has_a_bounded_usable_receipt():
    from backend.infrastructure.settings.model_verification import SignedModelVerification
    verifier = SignedModelVerification(Fernet.generate_key().decode())
    binding = {"base_url": "https://models.example.com/" + "中" * 1800, "model": "测" * 200,
               "credential_fingerprint": verifier.fingerprint("synthetic")}
    token = verifier.issue(binding)
    assert len(token) <= 4096
    verifier.verify(token, binding)


def test_old_tool_receipt_is_not_a_business_check_receipt(monkeypatch):
    from backend.infrastructure.settings.model_verification import SignedModelVerification
    from backend.domain.errors import ApplicationError
    verifier = SignedModelVerification(Fernet.generate_key().decode())
    with monkeypatch.context() as context:
        context.setattr("backend.infrastructure.settings.model_verification.PROBE_VERSION", "generation-tool-v1")
        old = verifier.issue({"user_id": "a"})
    with pytest.raises(ApplicationError):
        verifier.verify(old, {"user_id": "a"})
