from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from backend.schemas import AuthenticatedUser


PasswordChangeStatus = Literal[
    "changed",
    "current_password_invalid",
    "password_unchanged",
    "token_invalid",
]


@dataclass(frozen=True)
class PasswordChangeResult:
    status: PasswordChangeStatus
    token_version: int | None = None


@runtime_checkable
class IdentityRepository(Protocol):
    def register(
        self,
        username: str | None,
        email: str | None,
        phone: str | None,
        password: str,
        display_name: str,
    ) -> AuthenticatedUser: ...

    def authenticate(self, identifier: str, password: str) -> AuthenticatedUser | None: ...

    def get_by_id(self, user_id: str) -> AuthenticatedUser | None: ...

    def verify_user_password(self, user_id: str, password: str) -> bool: ...

    def replace_password(self, user_id: str, password: str) -> bool: ...

    def change_password_and_rotate_version(
        self,
        user_id: str,
        expected_token_version: int,
        current_password: str,
        new_password: str,
    ) -> PasswordChangeResult: ...

    def get_token_version(self, user_id: str) -> int | None: ...

    def rotate_token_version(
        self,
        user_id: str,
        expected_token_version: int | None = None,
    ) -> int | None: ...

    def validate_token_version(self, user_id: str, token_version: int) -> AuthenticatedUser | None: ...

    def delete_identity(self, user_id: str) -> bool: ...
