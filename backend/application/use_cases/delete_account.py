from __future__ import annotations

import re
import shutil
from pathlib import Path

from backend.application.ports.identity_repository import IdentityRepository
from backend.domain.errors import ApplicationError, account_delete_failed_error
from backend.schemas import AuthenticatedPrincipal


USER_ID_PATTERN = re.compile(r"[0-9a-f]{32}")


class DeleteAccount:
    def __init__(self, data_dir: Path, identities: IdentityRepository) -> None:
        self.data_dir = Path(data_dir)
        self.identities = identities

    def execute(
        self,
        principal: AuthenticatedPrincipal,
        *,
        password: str,
        confirmation: str,
    ) -> None:
        if confirmation != "DELETE":
            raise ApplicationError(
                code="ACCOUNT_DELETE_CONFIRMATION_INVALID",
                message='Enter "DELETE" to confirm account deletion.',
                status_code=422,
            )

        user_id = principal.user.user_id
        if USER_ID_PATTERN.fullmatch(user_id) is None:
            raise account_delete_failed_error()
        try:
            password_is_valid = self.identities.verify_user_password(user_id, password)
        except OSError:
            raise account_delete_failed_error() from None
        if not password_is_valid:
            raise ApplicationError(
                code="ACCOUNT_CURRENT_PASSWORD_INVALID",
                message="The current password is incorrect.",
                status_code=400,
            )

        users_root = self.data_dir / "users"
        user_root = users_root / user_id
        try:
            if users_root.is_symlink() or user_root.is_symlink():
                raise ValueError("Account storage cannot be a symbolic link")
            resolved_users_root = users_root.resolve(strict=False)
            resolved_user_root = user_root.resolve(strict=False)
            if (
                resolved_user_root.parent != resolved_users_root
                or resolved_user_root.name != user_id
            ):
                raise ValueError("Account storage escaped its boundary")
            shutil.rmtree(user_root)
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            raise account_delete_failed_error() from None
        try:
            self.identities.delete_identity(user_id)
        except OSError:
            raise account_delete_failed_error() from None
