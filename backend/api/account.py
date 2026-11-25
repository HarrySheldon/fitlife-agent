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
from backend.api.coach_conversations import get_coach_admission_service
from backend.application.use_cases.coach_turns import CoachTurnService
from backend.infrastructure.auth.sqlite_identity_repository import SQLiteIdentityRepository
from backend.infrastructure.repositories.sqlite_profile_target_repository import (
    SQLiteProfileTargetRepository,
)
from backend.infrastructure.repositories.sqlite_coach_conversation_repository import (
    SQLiteCoachConversationRepository,
)
from backend.infrastructure.settings.sqlite_model_connection_repository import SQLiteModelConnectionRepository
from backend.infrastructure.settings.sqlite_user_preferences_repository import SQLiteUserPreferencesRepository
from backend.infrastructure.sqlite.runtime import get_database
from backend.infrastructure.repositories.sqlite_entry_task_lifecycle import SQLiteEntryTaskLifecycleRepository
from backend.infrastructure.repositories.plan_repository_factory import build_plan_repository
from backend.infrastructure.repositories.sqlite_plan_adjustment_repository import SQLitePlanAdjustmentRepository
from backend.infrastructure.repositories.sqlite_plan_repository import SQLitePlanRepository
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
    admission: CoachTurnService = Depends(get_coach_admission_service),
):
    settings = get_settings()
    language = language_for_request(request, principal.user)
    setattr(request.state, REQUEST_LANGUAGE_STATE_KEY, language)
    # Stop the account's model call before its rows disappear. Leaving it running
    # would let a worker keep billing after the account that asked is gone.
    admission.cancel_active_for_account(principal.user.user_id)
    database = get_database()
    DeleteAccount(
        settings.data_dir,
        SQLiteIdentityRepository(database, settings.data_dir),
        SQLiteProfileTargetRepository(database),
        coach_conversations=SQLiteCoachConversationRepository(database),
        # Unconditional, not mode-dependent: a deletion must not depend on the
        # plan store being configured correctly, and rows left behind are the one
        # thing an account deletion cannot leave behind.
        plans=SQLitePlanRepository(database),
        # Tasks, rounds, candidates and receipts. Without this the plans would be
        # gone but the record of what the user asked to change would remain.
        plan_tasks=SQLitePlanAdjustmentRepository(database),
        user_preferences=SQLiteUserPreferencesRepository(database, settings.data_dir),
        model_connections=SQLiteModelConnectionRepository(database, settings.data_dir),
    ).execute(
        principal,
        password=payload.password,
        confirmation=payload.confirmation,
    )
    request.app.state.model_preview_limiter.clear_user(principal.user.user_id)
    return ok(
        None,
        translate_public_message("ACCOUNT_DELETED", language),
    )


@router.get("/export")
def export_account_data(
    principal: AuthenticatedPrincipal = Depends(require_current_principal),
):
    settings = get_settings()
    database = get_database()
    archive = ExportAccountData(
        settings.data_dir,
        SQLiteIdentityRepository(database, settings.data_dir),
        SQLiteModelConnectionRepository(database, settings.data_dir),
        user_preferences=SQLiteUserPreferencesRepository(database, settings.data_dir),
        entry_tasks=SQLiteEntryTaskLifecycleRepository(database),
        coach_conversations=SQLiteCoachConversationRepository(database),
        # The authoritative store, so an export of a SQLite-backed deployment
        # contains the plans rather than an empty directory.
        plans=build_plan_repository(settings),
        plan_tasks=SQLitePlanAdjustmentRepository(database),
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
    admission: CoachTurnService = Depends(get_coach_admission_service),
):
    repository = SQLiteIdentityRepository(get_database(), get_settings().data_dir)
    session = ChangePassword(repository, _issue_session).execute(
        principal,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    admission.cancel_active_for_account(principal.user.user_id)
    return ok(
        session.model_dump(),
        message_for_request("ACCOUNT_PASSWORD_CHANGED", request, principal.user),
    )


@router.post("/sessions/revoke-others")
def revoke_other_sessions(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_current_principal),
    admission: CoachTurnService = Depends(get_coach_admission_service),
):
    repository = SQLiteIdentityRepository(get_database(), get_settings().data_dir)
    session = RevokeOtherSessions(repository, _issue_session).execute(principal)
    admission.cancel_active_for_account(principal.user.user_id)
    return ok(
        session.model_dump(),
        message_for_request("ACCOUNT_SESSIONS_REVOKED", request, principal.user),
    )


def _issue_session(user: AuthenticatedUser, token_version: int) -> AuthSession:
    return AuthSession(
        access_token=create_access_token(user, token_version),
        user=user,
    )
