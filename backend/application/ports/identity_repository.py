from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.schemas import AuthenticatedUser


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
        current_password: str,
        new_password: str,
    ) -> int | None: ...

    def get_token_version(self, user_id: str) -> int | None: ...

    def rotate_token_version(self, user_id: str) -> int | None: ...

    def validate_token_version(self, user_id: str, token_version: int) -> AuthenticatedUser | None: ...

    def delete_identity(self, user_id: str) -> bool: ...
