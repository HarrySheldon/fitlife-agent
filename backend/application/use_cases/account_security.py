from __future__ import annotations

from collections.abc import Callable

from backend.application.ports.identity_repository import IdentityRepository
from backend.domain.errors import ApplicationError
from backend.schemas import AuthSession, AuthenticatedUser


SessionIssuer = Callable[[AuthenticatedUser, int], AuthSession]


class ChangePassword:
    def __init__(self, repository: IdentityRepository, issue_session: SessionIssuer) -> None:
        self.repository = repository
        self.issue_session = issue_session

    def execute(
        self,
        user: AuthenticatedUser,
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
        if current_password == new_password:
            if not self.repository.verify_user_password(user.user_id, current_password):
                raise _current_password_invalid()
            raise ApplicationError(
                code="ACCOUNT_PASSWORD_UNCHANGED",
                message="The new password must differ from the current password.",
                status_code=409,
            )
        token_version = self.repository.change_password_and_rotate_version(
            user.user_id,
            current_password,
            new_password,
        )
        if token_version is None:
            raise _current_password_invalid()
        return self.issue_session(user, token_version)


class RevokeOtherSessions:
    def __init__(self, repository: IdentityRepository, issue_session: SessionIssuer) -> None:
        self.repository = repository
        self.issue_session = issue_session

    def execute(self, user: AuthenticatedUser) -> AuthSession:
        token_version = self.repository.rotate_token_version(user.user_id)
        if token_version is None:
            raise ApplicationError(
                code="AUTH_TOKEN_INVALID",
                message="The session is invalid or has expired.",
                status_code=401,
            )
        return self.issue_session(user, token_version)


def _current_password_invalid() -> ApplicationError:
    return ApplicationError(
        code="ACCOUNT_CURRENT_PASSWORD_INVALID",
        message="The current password is incorrect.",
        status_code=400,
    )
