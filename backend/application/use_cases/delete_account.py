from __future__ import annotations

import os
import re
import shutil
import stat
from pathlib import Path
from uuid import uuid4

from backend.application.ports.identity_repository import IdentityRepository
from backend.domain.errors import ApplicationError, account_delete_failed_error
from backend.infrastructure.user_lifecycle import user_lifecycle_guard
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
            with user_lifecycle_guard(self.data_dir, user_id) as lifecycle:
                result = self.identities.confirm_and_delete_account(
                    user_id,
                    principal.token_version,
                    password,
                    lambda: self._cleanup_storage(user_id),
                )
                if result == "deleted":
                    lifecycle.mark_deleted()
        except (OSError, ValueError):
            raise account_delete_failed_error() from None
        if result == "token_invalid":
            raise ApplicationError(
                code="AUTH_TOKEN_INVALID",
                message="The session is invalid or has expired.",
                status_code=401,
            )
        if result == "current_password_invalid":
            raise ApplicationError(
                code="ACCOUNT_CURRENT_PASSWORD_INVALID",
                message="The current password is incorrect.",
                status_code=400,
            )
        if result != "deleted":
            raise account_delete_failed_error()

    def _cleanup_storage(self, user_id: str) -> None:
        users_root = self.data_dir / "users"
        user_root = users_root / user_id
        try:
            if (
                users_root.is_symlink()
                or user_root.is_symlink()
                or (_entry_exists(users_root) and _entry_is_link_or_reparse(users_root))
                or (_entry_exists(user_root) and _entry_is_link_or_reparse(user_root))
            ):
                raise ValueError("Account storage cannot be a symbolic link")
            resolved_users_root = users_root.resolve(strict=False)
            resolved_user_root = user_root.resolve(strict=False)
            if (
                resolved_user_root.parent != resolved_users_root
                or resolved_user_root.name != user_id
            ):
                raise ValueError("Account storage escaped its boundary")
            quarantines = list(
                users_root.glob(f".delete-{user_id}-*.quarantine")
            )
            if _entry_exists(user_root):
                quarantine = users_root / f".delete-{user_id}-{uuid4().hex}.quarantine"
                try:
                    os.replace(user_root, quarantine)
                except FileNotFoundError:
                    if _entry_exists(user_root):
                        raise
                else:
                    quarantines.append(quarantine)
            for quarantine in quarantines:
                _cleanup_quarantine(quarantine, resolved_users_root)
        except (OSError, ValueError):
            raise account_delete_failed_error() from None


def _entry_is_link_or_reparse(path: Path) -> bool:
    entry = os.lstat(path)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(entry, "st_file_attributes", 0)
    return stat.S_ISLNK(entry.st_mode) or bool(attributes & reparse_flag)


def _unlink_reparse_entry(path: Path) -> None:
    entry = os.lstat(path)
    if stat.S_ISDIR(entry.st_mode):
        os.rmdir(path)
    else:
        path.unlink()


def _entry_exists(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


def _cleanup_quarantine(quarantine: Path, resolved_users_root: Path) -> None:
    if _entry_is_link_or_reparse(quarantine):
        _unlink_reparse_entry(quarantine)
        raise ValueError("Quarantined account storage is an untrusted link")
    resolved_quarantine = quarantine.resolve(strict=True)
    if resolved_quarantine.parent != resolved_users_root:
        raise ValueError("Quarantined account storage escaped its boundary")
    try:
        shutil.rmtree(quarantine)
    except FileNotFoundError:
        if _entry_exists(quarantine):
            raise OSError("Quarantine cleanup did not remove the account root") from None
    if _entry_exists(quarantine):
        raise OSError("Quarantine cleanup did not remove the account root")
