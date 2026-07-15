from __future__ import annotations

from collections.abc import Callable

from backend.application.ports.identity_repository import IdentityRepository
from backend.domain.errors import ApplicationError
from backend.schemas import AuthSession, AuthenticatedPrincipal, AuthenticatedUser


SessionIssuer = Callable[[AuthenticatedUser, int], AuthSession]


class ChangePassword:
    def __init__(self, repository: IdentityRepository, issue_session: SessionIssuer) -> None:
        self.repository = repository
        self.issue_session = issue_session

    def execute(
        self,
        principal: AuthenticatedPrincipal,
        *,
        current_password: str,
        new_password: str,
    ) -> AuthSession:
        if not 8 <= len(new_password) <= 128:
            raise ApplicationError(
                code="ACCOUNT_PASSWORD_POLICY",
                message="The new password must be between 8 and 128 characters.",
                status_code=422,
            )
        next_version = principal.token_version + 1
        candidate = self.issue_session(principal.user, next_version)
        result = self.repository.change_password_and_rotate_version(
            principal.user.user_id,
            principal.token_version,
            current_password,
            new_password,
        )
        if result.status == "token_invalid":
            raise _token_invalid()
        if result.status == "current_password_invalid":
            raise _current_password_invalid()
        if result.status == "password_unchanged":
            raise ApplicationError(
                code="ACCOUNT_PASSWORD_UNCHANGED",
                message="The new password must differ from the current password.",
                status_code=409,
            )
        if result.status != "changed" or result.token_version != next_version:
            raise _token_invalid()
        return candidate


class RevokeOtherSessions:
    def __init__(self, repository: IdentityRepository, issue_session: SessionIssuer) -> None:
        self.repository = repository
        self.issue_session = issue_session

    def execute(self, principal: AuthenticatedPrincipal) -> AuthSession:
        next_version = principal.token_version + 1
        candidate = self.issue_session(principal.user, next_version)
        token_version = self.repository.rotate_token_version(
            principal.user.user_id,
            expected_token_version=principal.token_version,
        )
        if token_version != next_version:
            raise _token_invalid()
        return candidate


def _current_password_invalid() -> ApplicationError:
    return ApplicationError(
        code="ACCOUNT_CURRENT_PASSWORD_INVALID",
        message="The current password is incorrect.",
        status_code=400,
    )


def _token_invalid() -> ApplicationError:
    return ApplicationError(
        code="AUTH_TOKEN_INVALID",
        message="The session is invalid or has expired.",
        status_code=401,
    )
