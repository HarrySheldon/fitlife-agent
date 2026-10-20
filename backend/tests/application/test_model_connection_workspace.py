import pytest

from backend.tests.application.test_model_connection_preview import setup_connection
from backend.domain.errors import ApplicationError
from backend.domain.model_connection_setup import ModelActivationInput


def test_activation_needs_matching_receipt_and_preserves_active_on_failure(setup_connection):
    from backend.application.use_cases.model_connection_workspace import ModelConnectionWorkspaceService
    context = setup_connection
    service = ModelConnectionWorkspaceService(context.service)
    token = context.service.test("a", context.payload)["verification_token"]
    bad = ModelActivationInput(**context.payload.model_dump(exclude={"model"}), model="different", verification_token=token)
    with pytest.raises(ApplicationError) as rejected:
        service.activate("a", bad)
    assert rejected.value.code == "MODEL_VERIFICATION_REQUIRED"
    assert context.repo.get("a").model == "old"
    payload = ModelActivationInput(**context.payload.model_dump(), verification_token=token)
    result = service.activate("a", payload)
    assert result.active.enabled
    assert result.active.model == "candidate"
    assert result.active.generation_status == result.active.structured_status == "passed"
    assert result.active.tool_status == "not_run"
    with pytest.raises(ApplicationError):
        service.activate("a", payload)


def test_draft_save_keeps_active_and_key_clear_invalidates_prior_receipt(setup_connection):
    from backend.application.use_cases.model_connection_workspace import ModelConnectionWorkspaceService
    context = setup_connection
    service = ModelConnectionWorkspaceService(context.service)
    result = service.save_draft("a", context.payload)
    assert result.active.model == "old"
    assert result.active.enabled
    assert not result.draft.enabled
    assert context.calls == []
    updated = context.payload.model_copy(update={"expected_revision": result.revision})
    token = context.service.test("a", updated)["verification_token"]
    cleared = service.clear_credential("a", result.revision, "active")
    assert not cleared.active.enabled
    assert not cleared.active.api_key_configured
    assert cleared.draft.api_key_configured
    with pytest.raises(ApplicationError):
        service.activate("a", ModelActivationInput(**updated.model_dump(), verification_token=token))


def test_deleted_account_cannot_be_recreated_by_delayed_activation(setup_connection):
    from backend.application.use_cases.model_connection_workspace import ModelConnectionWorkspaceService
    from backend.infrastructure.user_lifecycle import user_lifecycle_guard
    context = setup_connection
    token = context.service.test("a", context.payload)["verification_token"]
    with user_lifecycle_guard(context.repo.data_dir, "a") as guard:
        guard.mark_deleted()
    with pytest.raises(ApplicationError) as rejected:
        ModelConnectionWorkspaceService(context.service).activate("a",
            ModelActivationInput(**context.payload.model_dump(), verification_token=token))
    assert rejected.value.code == "AUTH_TOKEN_INVALID"


@pytest.mark.parametrize("change", [{"model": "other"}, {"protocol": "responses"},
    {"base_url": "https://other.example.com/v1"}, {"api_key": "different-key"}])
def test_material_changes_cannot_reuse_receipt(setup_connection, change):
    from backend.application.use_cases.model_connection_workspace import ModelConnectionWorkspaceService
    context = setup_connection
    token = context.service.test("a", context.payload)["verification_token"]
    changed = ModelActivationInput(**{**context.payload.model_dump(), **change}, verification_token=token)
    with pytest.raises(ApplicationError) as rejected:
        ModelConnectionWorkspaceService(context.service).activate("a", changed)
    assert rejected.value.code == "MODEL_VERIFICATION_REQUIRED"
    assert context.repo.get("a").model == "old"


def test_short_credential_is_not_returned_as_its_own_hint(setup_connection):
    from backend.application.use_cases.model_connection_workspace import ModelConnectionWorkspaceService
    from pydantic import SecretStr
    context = setup_connection
    payload = context.payload.model_copy(update={"api_key": SecretStr("xq7")})
    saved = ModelConnectionWorkspaceService(context.service).save_draft("a", payload)
    assert saved.draft.api_key_hint == "********"
    assert "xq7" not in saved.model_dump_json()
