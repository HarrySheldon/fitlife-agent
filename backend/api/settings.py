from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.dependencies import require_current_user
from backend.api.utils import ok
from backend.application.use_cases.model_settings import (
    ClearModelApiKey,
    GetModelSettings,
    ListAvailableModels,
    ModelSettingsUpdate,
    SaveModelSettings,
    TestModelConnection,
)
from backend.config import get_settings
from backend.infrastructure.model_gateway.factory import create_model_gateway
from backend.infrastructure.settings.fernet_cipher import FernetCredentialCipher
from backend.infrastructure.settings.file_model_connection_repository import FileModelConnectionRepository
from backend.schemas import AuthenticatedUser, ModelSettingsUpdateRequest


router = APIRouter(prefix="/settings")


@router.get("/model")
def get_model_settings(user: AuthenticatedUser = Depends(require_current_user)):
    repository = _repository()
    result = GetModelSettings(repository).execute(user.user_id)
    return ok(result.model_dump(), processing_mode="deterministic")


@router.put("/model")
def save_model_settings(
    request: ModelSettingsUpdateRequest,
    user: AuthenticatedUser = Depends(require_current_user),
):
    repository = _repository()
    result = SaveModelSettings(repository, _cipher()).execute(
        user.user_id,
        ModelSettingsUpdate(**request.model_dump()),
    )
    return ok(result.model_dump(), "Model settings saved", processing_mode="deterministic")


@router.delete("/model/api-key")
def clear_model_api_key(user: AuthenticatedUser = Depends(require_current_user)):
    result = ClearModelApiKey(_repository()).execute(user.user_id)
    return ok(result.model_dump(), "API key cleared", processing_mode="deterministic")


@router.post("/model/models")
def list_model_options(user: AuthenticatedUser = Depends(require_current_user)):
    result = ListAvailableModels(_repository(), _cipher(), create_model_gateway).execute(user.user_id)
    return ok({"models": result}, processing_mode="agent")


@router.post("/model/test")
def test_model_connection(user: AuthenticatedUser = Depends(require_current_user)):
    result = TestModelConnection(_repository(), _cipher(), create_model_gateway).execute(user.user_id)
    return ok(result.model_dump(), "Model connection verified", processing_mode="agent")


def _repository() -> FileModelConnectionRepository:
    return FileModelConnectionRepository(get_settings().data_dir)


def _cipher() -> FernetCredentialCipher | None:
    key = get_settings().settings_encryption_key
    if not key:
        return None
    try:
        return FernetCredentialCipher(key)
    except ValueError:
        return None
