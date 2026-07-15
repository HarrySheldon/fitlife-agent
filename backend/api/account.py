from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.api.dependencies import require_current_principal
from backend.api.utils import ok
from backend.application.use_cases.account_security import ChangePassword, RevokeOtherSessions
from backend.config import get_settings
from backend.i18n import message_for_request
from backend.infrastructure.auth.file_identity_repository import FileIdentityRepository
from backend.schemas import (
    AccountPasswordChangeRequest,
    AuthSession,
    AuthenticatedPrincipal,
    AuthenticatedUser,
)
from backend.tools.auth_store import create_access_token


router = APIRouter(prefix="/account")


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
