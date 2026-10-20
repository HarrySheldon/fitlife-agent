from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, Query

from backend.api.dependencies import require_current_user
from backend.api.utils import ok
from backend.application.use_cases.model_settings import GetModelSettings
from backend.application.use_cases.user_preferences import GetUserPreferences, UpdateUserPreferences
from backend.application.use_cases.model_connection_preview import ModelConnectionPreview, setup_error
from backend.application.use_cases.model_connection_workspace import ModelConnectionWorkspaceService
from backend.domain.model_connection_setup import ModelConnectionInput, ModelActivationInput, ModelRevisionInput
from backend.domain.model_endpoint_policy import ModelEndpointPolicy
from backend.domain.model_provider import DEFAULT_PROVIDERS
from backend.config import get_settings
from backend.infrastructure.model_gateway.preview_process import create_preview_gateway as create_model_gateway
from backend.infrastructure.settings.fernet_cipher import FernetCredentialCipher
from backend.infrastructure.settings.file_model_connection_repository import FileModelConnectionRepository
from backend.infrastructure.settings.file_user_preferences_repository import FileUserPreferencesRepository
from backend.infrastructure.settings.model_verification import SignedModelVerification
from backend.domain.errors import model_verification_required_error
from backend.i18n import message_for_request
from backend.schemas import AuthenticatedUser, ModelSettingsUpdateRequest, UserPreferencesUpdateRequest


router = APIRouter(prefix="/settings")


@router.get("/preferences")
def get_preferences(
    user: AuthenticatedUser = Depends(require_current_user),
    accept_language: str | None = Header(default=None),
    x_timezone: str | None = Header(default=None, alias="X-Timezone"),
):
    result = GetUserPreferences(_preferences_repository()).execute(
        user.user_id,
        language_hint=accept_language,
        timezone_hint=x_timezone,
    )
    return ok(result.model_dump(), processing_mode="deterministic")


@router.patch("/preferences")
def update_preferences(
    request: Request,
    payload: UserPreferencesUpdateRequest,
    user: AuthenticatedUser = Depends(require_current_user),
):
    result = UpdateUserPreferences(_preferences_repository()).execute(
        user.user_id,
        **payload.model_dump(exclude_unset=True),
    )
    return ok(
        result.model_dump(),
        message_for_request("PREFERENCES_SAVED", request, user),
        processing_mode="deterministic",
    )


@router.get("/model")
def get_model_settings(user: AuthenticatedUser = Depends(require_current_user)):
    repository = _repository()
    result = GetModelSettings(repository).execute(user.user_id)
    return ok(result.model_dump(), processing_mode="deterministic")


@router.put("/model")
def save_model_settings(
    request: Request,
    payload: ModelSettingsUpdateRequest,
    user: AuthenticatedUser = Depends(require_current_user),
):
    if payload.enabled and not payload.verification_token:
        raise model_verification_required_error()
    if payload.expected_revision is None:
        raise setup_error("MODEL_CONFIGURATION_CONFLICT", "Reload the configuration and provide its revision.")
    current = _repository().get_workspace(user.user_id)
    source = current.draft or current.active
    values = dict(provider_id=payload.provider, protocol=payload.protocol,
        base_url=payload.base_url or "https://api.openai.com/v1", model=payload.model,
        expected_revision=payload.expected_revision,
        credential_mode="new" if payload.api_key else ("reuse_draft" if current.draft else "reuse_active"),
        confirm_credential_reuse=payload.confirm_credential_reuse)
    if payload.api_key:
        values["api_key"] = payload.api_key
    if not source and not payload.api_key:
        raise setup_error("MODEL_CREDENTIAL_REQUIRED", "Provide a model credential.", 422)
    workspace = _workspace_service(request)
    if payload.enabled:
        result = workspace.activate(user.user_id, ModelActivationInput(**values, verification_token=payload.verification_token)).active
    else:
        result = workspace.save_draft(user.user_id, ModelConnectionInput(**values)).draft
    return ok(result.model_dump(), message_for_request("MODEL_SETTINGS_SAVED", request, user), processing_mode="deterministic")


@router.delete("/model/api-key")
def clear_model_api_key(request: Request, slot: str = Query("active", pattern="^(active|draft)$"),
                        expected_revision: int | None = Query(None, ge=0),
                        user: AuthenticatedUser = Depends(require_current_user)):
    if expected_revision is None:
        raise setup_error("MODEL_CONFIGURATION_CONFLICT", "Provide the current configuration revision.")
    result = _workspace_service(request).clear_credential(user.user_id, expected_revision, slot)
    return ok(result.model_dump(), processing_mode="deterministic")


@router.post("/model/models")
def list_model_options(request: Request, user: AuthenticatedUser = Depends(require_current_user)):
    result = _preview(request).list_models(user.user_id, _active_input(user.user_id))
    return ok(result, processing_mode="agent")


@router.post("/model/test")
def test_model_connection(request: Request, user: AuthenticatedUser = Depends(require_current_user)):
    payload = _active_input(user.user_id)
    result = _preview(request).test(user.user_id, payload)
    result.update(status="success" if result["verification_token"] else "failed", model=payload.model,
        protocol=payload.protocol, latency_ms=sum(result[name].get("latency_ms", 0) for name in ("generation", "structured")))
    return ok(result, processing_mode="agent")


@router.get("/model/providers")
def model_providers(user: AuthenticatedUser = Depends(require_current_user)):
    return ok({"providers": [item.model_dump() for item in DEFAULT_PROVIDERS.list()]}, processing_mode="deterministic")


@router.get("/model/workspace")
def model_workspace(user: AuthenticatedUser = Depends(require_current_user)):
    return ok(_repository().get_workspace(user.user_id).to_public().model_dump(), processing_mode="deterministic")


@router.post("/model/preview/models")
def preview_model_list(request: Request, payload: ModelConnectionInput, user: AuthenticatedUser = Depends(require_current_user)):
    return ok(_preview(request).list_models(user.user_id, payload), processing_mode="agent")


@router.post("/model/preview/test")
def preview_model_test(request: Request, payload: ModelConnectionInput, user: AuthenticatedUser = Depends(require_current_user)):
    return ok(_preview(request).test(user.user_id, payload), processing_mode="agent")


@router.put("/model/draft")
def save_model_draft(request: Request, payload: ModelConnectionInput, user: AuthenticatedUser = Depends(require_current_user)):
    return ok(_workspace_service(request).save_draft(user.user_id, payload).model_dump(), processing_mode="deterministic")


@router.post("/model/activate")
def activate_model(request: Request, payload: ModelActivationInput, user: AuthenticatedUser = Depends(require_current_user)):
    return ok(_workspace_service(request).activate(user.user_id, payload).model_dump(), processing_mode="deterministic")


@router.post("/model/disable")
def disable_model(request: Request, payload: ModelRevisionInput, user: AuthenticatedUser = Depends(require_current_user)):
    return ok(_workspace_service(request).disable(user.user_id, payload.expected_revision).model_dump(), processing_mode="deterministic")


def _active_input(user_id):
    workspace = _repository().get_workspace(user_id)
    connection = workspace.active
    if connection is None or not connection.encrypted_api_key:
        from backend.domain.errors import ai_not_configured_error
        raise ai_not_configured_error()
    return ModelConnectionInput(provider_id=connection.provider_id or connection.provider, protocol=connection.protocol,
        base_url=connection.base_url or "https://api.openai.com/v1", model=connection.model,
        expected_revision=workspace.revision, credential_mode="reuse_active")


def _endpoint_policy():
    return ModelEndpointPolicy()


def _preview(request):
    key = get_settings().settings_encryption_key
    cipher = _cipher()
    return ModelConnectionPreview(_repository(), cipher, SignedModelVerification(key) if cipher else None,
        create_model_gateway, _endpoint_policy(), request.app.state.model_preview_limiter)


def _workspace_service(request):
    return ModelConnectionWorkspaceService(_preview(request))


def _repository() -> FileModelConnectionRepository:
    return FileModelConnectionRepository(get_settings().data_dir)


def _preferences_repository() -> FileUserPreferencesRepository:
    return FileUserPreferencesRepository(get_settings().data_dir)


def _cipher() -> FernetCredentialCipher | None:
    key = get_settings().settings_encryption_key
    if not key:
        return None
    try:
        return FernetCredentialCipher(key)
    except ValueError:
        return None
