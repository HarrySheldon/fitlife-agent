from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from backend.api.dependencies import require_current_principal
from backend.api.utils import ok
from backend.application.use_cases.account_security import ChangePassword, RevokeOtherSessions
from backend.application.use_cases.delete_account import DeleteAccount
from backend.application.use_cases.export_account_data import ExportAccountData
from backend.config import get_settings
from backend.i18n import (
    REQUEST_LANGUAGE_STATE_KEY,
    language_for_request,
    message_for_request,
    translate_public_message,
)
from backend.infrastructure.auth.file_identity_repository import FileIdentityRepository
from backend.infrastructure.settings.file_model_connection_repository import FileModelConnectionRepository
from backend.schemas import (
    AccountDeleteRequest,
    AccountPasswordChangeRequest,
    AuthSession,
    AuthenticatedPrincipal,
    AuthenticatedUser,
)
from backend.tools.auth_store import create_access_token


router = APIRouter(prefix="/account")
_EXPORT_FILENAME = "account-data-export.zip"


@router.delete("")
def delete_account(
    request: Request,
    payload: AccountDeleteRequest,
    principal: AuthenticatedPrincipal = Depends(require_current_principal),
):
    settings = get_settings()
    language = language_for_request(request, principal.user)
    setattr(request.state, REQUEST_LANGUAGE_STATE_KEY, language)
    DeleteAccount(
        settings.data_dir,
        FileIdentityRepository(settings.data_dir),
    ).execute(
        principal,
        password=payload.password,
        confirmation=payload.confirmation,
    )
    return ok(
        None,
        translate_public_message("ACCOUNT_DELETED", language),
    )


@router.get("/export")
def export_account_data(
    principal: AuthenticatedPrincipal = Depends(require_current_principal),
):
    settings = get_settings()
    archive = ExportAccountData(
        settings.data_dir,
        FileIdentityRepository(settings.data_dir),
        FileModelConnectionRepository(settings.data_dir),
    ).execute(principal.user.user_id)
    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{_EXPORT_FILENAME}"',
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )


@router.post("/password/change")
def change_password(
    request: Request,
    payload: AccountPasswordChangeRequest,
    principal: AuthenticatedPrincipal = Depends(require_current_principal),
):
    repository = FileIdentityRepository(get_settings().data_dir)
    session = ChangePassword(repository, _issue_session).execute(
        principal,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return ok(
        session.model_dump(),
        message_for_request("ACCOUNT_PASSWORD_CHANGED", request, principal.user),
    )


@router.post("/sessions/revoke-others")
def revoke_other_sessions(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_current_principal),
):
    repository = FileIdentityRepository(get_settings().data_dir)
    session = RevokeOtherSessions(repository, _issue_session).execute(principal)
    return ok(
        session.model_dump(),
        message_for_request("ACCOUNT_SESSIONS_REVOKED", request, principal.user),
    )


def _issue_session(user: AuthenticatedUser, token_version: int) -> AuthSession:
    return AuthSession(
        access_token=create_access_token(user, token_version),
        user=user,
    )
