from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from backend.application.ports.identity_repository import IdentityRepository
from backend.infrastructure.auth.file_identity_repository import FileIdentityRepository, hash_password


def test_concurrent_registrations_are_atomic_and_do_not_lose_users():
    data_dir = Path(".tmp") / "pytest-identity" / uuid4().hex

    def register(index: int):
        repository = FileIdentityRepository(data_dir)
        return repository.register(
            username=f"user-{index}",
            email=f"user-{index}@example.com",
            phone=None,
            password="password123",
            display_name=f"User {index}",
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        users = list(executor.map(register, range(8)))

    stored = json.loads((data_dir / "users.json").read_text(encoding="utf-8"))

    assert isinstance(FileIdentityRepository(data_dir), IdentityRepository)
    assert {user.user_id for user in users} == {entry["user_id"] for entry in stored}
    assert len(stored) == 8


def test_legacy_user_missing_token_version_is_migrated_as_version_zero():
    data_dir = Path(".tmp") / "pytest-identity" / uuid4().hex
    data_dir.mkdir(parents=True)
    users_path = data_dir / "users.json"
    users_path.write_text(
        json.dumps(
            [
                {
                    "user_id": "legacy-user",
                    "username": "legacy",
                    "email": "legacy@example.com",
                    "phone": "13800138000",
                    "display_name": "Legacy User",
                    "password_hash": hash_password("password123"),
                    "created_at": "2026-07-01T00:00:00+00:00",
                }
            ]
        ),
        encoding="utf-8",
    )

    token_version = FileIdentityRepository(data_dir).get_token_version("legacy-user")

    stored = json.loads(users_path.read_text(encoding="utf-8"))
    assert token_version == 0
    assert stored[0]["token_version"] == 0


@pytest.mark.parametrize("identifier", ["FIT_USER", "FIT@EXAMPLE.COM", "13800138000"])
def test_authenticate_preserves_normalized_username_email_and_phone_login(identifier):
    data_dir = Path(".tmp") / "pytest-identity" / uuid4().hex
    repository = FileIdentityRepository(data_dir)
    registered = repository.register(
        username="Fit_User",
        email="Fit@Example.com",
        phone="+8613800138000",
        password="password123",
        display_name="Fit User",
    )

    authenticated = repository.authenticate(identifier, "password123")

    assert authenticated == registered


def test_identity_security_lifecycle_uses_current_password_and_token_version():
    data_dir = Path(".tmp") / "pytest-identity" / uuid4().hex
    repository = FileIdentityRepository(data_dir)
    user = repository.register("security-user", None, None, "password123", "Security User")

    assert repository.get_by_id(user.user_id) == user
    assert repository.verify_user_password(user.user_id, "password123") is True
    assert repository.replace_password(user.user_id, "replacement123") is True
    assert repository.verify_user_password(user.user_id, "password123") is False
    assert repository.verify_user_password(user.user_id, "replacement123") is True
    assert repository.rotate_token_version(user.user_id) == 1
    assert repository.validate_token_version(user.user_id, 0) is None
    assert repository.validate_token_version(user.user_id, 1) == user
    assert repository.delete_identity(user.user_id) is True
    assert repository.delete_identity(user.user_id) is False
    assert repository.get_by_id(user.user_id) is None
