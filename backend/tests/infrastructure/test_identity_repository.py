from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from backend.application.ports.identity_repository import IdentityRepository
from backend.infrastructure.auth import file_identity_repository as identity_repository_module
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


def test_identity_write_replaces_from_same_directory_temporary_file(monkeypatch):
    data_dir = Path(".tmp") / "pytest-identity" / uuid4().hex
    repository = FileIdentityRepository(data_dir)
    replace_file = repository.replace_file
    replacements: list[tuple[Path, Path]] = []

    def observe_replace(source: Path, destination: Path) -> None:
        replacements.append((source, destination))
        replace_file(source, destination)

    monkeypatch.setattr(repository, "replace_file", observe_replace)

    repository.register("atomic-user", None, None, "password123", "Atomic User")

    assert len(replacements) == 1
    source, destination = replacements[0]
    assert destination == data_dir / "users.json"
    assert source.parent == destination.parent
    assert source != destination
    assert source.name.startswith("users.json.")
    assert source.suffix == ".tmp"
    assert not source.exists()
    assert json.loads(destination.read_text(encoding="utf-8"))[0]["username"] == "atomic-user"


def test_failed_identity_replacement_preserves_old_file_and_removes_temporary(monkeypatch):
    data_dir = Path(".tmp") / "pytest-identity" / uuid4().hex
    repository = FileIdentityRepository(data_dir)
    repository.register("existing-user", None, None, "password123", "Existing User")
    users_path = data_dir / "users.json"
    original = users_path.read_bytes()
    attempted_sources: list[Path] = []

    def fail_replace(source: Path, destination: Path) -> None:
        attempted_sources.append(source)
        assert source.exists()
        assert destination == users_path
        raise OSError("replacement failed")

    monkeypatch.setattr(repository, "replace_file", fail_replace)

    with pytest.raises(OSError, match="replacement failed"):
        repository.register("new-user", None, None, "password123", "New User")

    assert users_path.read_bytes() == original
    assert len(attempted_sources) == 1
    assert not attempted_sources[0].exists()
    assert list(data_dir.glob("users.json.*.tmp")) == []


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


@pytest.mark.parametrize(
    "password_hash",
    [
        f"pbkdf2_sha256$99999$c2FsdA${'A' * 43}",
        f"pbkdf2_sha256$1000001$c2FsdA${'A' * 43}",
        f"pbkdf2_sha256$120000${'A' * 129}${'A' * 43}",
        f"pbkdf2_sha256$120000$***${'A' * 43}",
        "pbkdf2_sha256$120000$c2FsdA$AA",
    ],
)
def test_authenticate_rejects_untrusted_hash_fields_before_pbkdf2(monkeypatch, password_hash):
    data_dir = Path(".tmp") / "pytest-identity" / uuid4().hex
    _write_identity_with_password_hash(data_dir, password_hash)

    def unexpected_pbkdf2(*args, **kwargs):
        raise AssertionError("malformed hashes must be rejected before PBKDF2")

    monkeypatch.setattr(identity_repository_module.hashlib, "pbkdf2_hmac", unexpected_pbkdf2)

    assert FileIdentityRepository(data_dir).authenticate("stored-user", "password123") is None


@pytest.mark.parametrize("error", [ValueError("invalid parameters"), OverflowError("iteration overflow")])
def test_authenticate_returns_failure_when_pbkdf2_rejects_valid_hash(monkeypatch, error):
    data_dir = Path(".tmp") / "pytest-identity" / uuid4().hex
    _write_identity_with_password_hash(data_dir, hash_password("password123"))

    def failing_pbkdf2(*args, **kwargs):
        raise error

    monkeypatch.setattr(identity_repository_module.hashlib, "pbkdf2_hmac", failing_pbkdf2)

    assert FileIdentityRepository(data_dir).authenticate("stored-user", "password123") is None


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


def _write_identity_with_password_hash(data_dir: Path, password_hash: str) -> None:
    data_dir.mkdir(parents=True)
    (data_dir / "users.json").write_text(
        json.dumps(
            [
                {
                    "user_id": "stored-user",
                    "username": "stored-user",
                    "email": None,
                    "phone": None,
                    "display_name": "Stored User",
                    "password_hash": password_hash,
                    "created_at": "2026-07-01T00:00:00+00:00",
                    "token_version": 0,
                }
            ]
        ),
        encoding="utf-8",
    )
