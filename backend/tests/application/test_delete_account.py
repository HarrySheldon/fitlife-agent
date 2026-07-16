from __future__ import annotations

from pathlib import Path
import shutil
from uuid import uuid4

import pytest

import backend.application.use_cases.delete_account as delete_module
from backend.application.use_cases.delete_account import DeleteAccount
from backend.domain.errors import ApplicationError
from backend.infrastructure.auth.file_identity_repository import FileIdentityRepository
from backend.schemas import AuthenticatedPrincipal


def make_data_dir() -> Path:
    return Path(".tmp") / "pytest-delete-account" / uuid4().hex


class TrackingIdentityRepository(FileIdentityRepository):
    def __init__(self, data_dir: Path, events: list[str]) -> None:
        super().__init__(data_dir)
        self.events = events

    def verify_user_password(self, user_id: str, password: str) -> bool:
        self.events.append("password_verified")
        return super().verify_user_password(user_id, password)

    def delete_identity(self, user_id: str) -> bool:
        self.events.append("identity_deleted")
        return super().delete_identity(user_id)


class RejectUnexpectedRepository:
    def verify_user_password(self, user_id: str, password: str) -> bool:
        raise AssertionError("password lookup must not run for an invalid target")

    def delete_identity(self, user_id: str) -> bool:
        raise AssertionError("identity deletion must not run for an invalid target")


class FailingPasswordLookupRepository:
    def verify_user_password(self, user_id: str, password: str) -> bool:
        raise PermissionError("private identity read detail")

    def delete_identity(self, user_id: str) -> bool:
        raise AssertionError("identity deletion must not follow a failed password lookup")


def test_confirmed_account_deletion_removes_only_authenticated_user_and_identity(monkeypatch):
    data_dir = make_data_dir()
    events: list[str] = []
    repository = TrackingIdentityRepository(data_dir, events)
    user = repository.register("delete-user", None, None, "password123", "Delete User")
    other = repository.register("keep-user", None, None, "password456", "Keep User")
    user_root = data_dir / "users" / user.user_id
    other_root = data_dir / "users" / other.user_id
    (user_root / "nested").mkdir(parents=True)
    (user_root / "nested" / "record.json").write_text("private", encoding="utf-8")
    other_root.mkdir(parents=True)
    (other_root / "record.json").write_text("untouched", encoding="utf-8")
    remove_tree = shutil.rmtree

    def track_storage_deletion(path: Path) -> None:
        events.append("storage_deleted")
        remove_tree(path)

    monkeypatch.setattr(delete_module.shutil, "rmtree", track_storage_deletion)

    DeleteAccount(data_dir, repository).execute(
        AuthenticatedPrincipal(user=user, token_version=0),
        password="password123",
        confirmation="DELETE",
    )

    assert events == ["password_verified", "storage_deleted", "identity_deleted"]
    assert not user_root.exists()
    assert repository.get_by_id(user.user_id) is None
    assert repository.get_by_id(other.user_id) == other
    assert (other_root / "record.json").read_text(encoding="utf-8") == "untouched"


def test_account_deletion_tolerates_already_missing_user_directory():
    data_dir = make_data_dir()
    repository = FileIdentityRepository(data_dir)
    user = repository.register("missing-files-user", None, None, "password123", "Missing Files")

    DeleteAccount(data_dir, repository).execute(
        AuthenticatedPrincipal(user=user, token_version=0),
        password="password123",
        confirmation="DELETE",
    )

    assert repository.get_by_id(user.user_id) is None


@pytest.mark.parametrize(
    ("password", "confirmation", "expected_code", "expected_events"),
    [
        (
            "password123",
            "delete",
            "ACCOUNT_DELETE_CONFIRMATION_INVALID",
            [],
        ),
        (
            "wrong-password",
            "DELETE",
            "ACCOUNT_CURRENT_PASSWORD_INVALID",
            ["password_verified"],
        ),
    ],
)
def test_invalid_confirmation_or_password_causes_no_mutation(
    password: str,
    confirmation: str,
    expected_code: str,
    expected_events: list[str],
):
    data_dir = make_data_dir()
    events: list[str] = []
    repository = TrackingIdentityRepository(data_dir, events)
    user = repository.register("reject-delete", None, None, "password123", "Reject Delete")
    user_root = data_dir / "users" / user.user_id
    user_root.mkdir(parents=True)
    marker = user_root / "record.json"
    marker.write_text("untouched", encoding="utf-8")

    with pytest.raises(ApplicationError) as raised:
        DeleteAccount(data_dir, repository).execute(
            AuthenticatedPrincipal(user=user, token_version=0),
            password=password,
            confirmation=confirmation,
        )

    assert raised.value.code == expected_code
    assert events == expected_events
    assert marker.read_text(encoding="utf-8") == "untouched"
    assert repository.get_by_id(user.user_id) == user


def test_account_deletion_rejects_traversal_user_id_before_any_mutation():
    data_dir = make_data_dir()
    outside = data_dir / "outside"
    outside.mkdir(parents=True)
    marker = outside / "record.json"
    marker.write_text("untouched", encoding="utf-8")
    user = FileIdentityRepository(data_dir).register(
        "invalid-target-user", None, None, "password123", "Invalid Target"
    )
    forged = user.model_copy(update={"user_id": "../outside"})

    with pytest.raises(ApplicationError) as raised:
        DeleteAccount(data_dir, RejectUnexpectedRepository()).execute(
            AuthenticatedPrincipal(user=forged, token_version=0),
            password="password123",
            confirmation="DELETE",
        )

    assert raised.value.code == "ACCOUNT_DELETE_FAILED"
    assert marker.read_text(encoding="utf-8") == "untouched"


def test_account_deletion_rejects_symlink_user_directory(monkeypatch):
    data_dir = make_data_dir()
    repository = FileIdentityRepository(data_dir)
    user = repository.register("symlink-user", None, None, "password123", "Symlink User")
    user_root = data_dir / "users" / user.user_id
    user_root.mkdir(parents=True)
    marker = user_root / "record.json"
    marker.write_text("untouched", encoding="utf-8")
    path_is_symlink = Path.is_symlink

    def report_user_root_as_symlink(path: Path) -> bool:
        return path == user_root or path_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", report_user_root_as_symlink)

    with pytest.raises(ApplicationError) as raised:
        DeleteAccount(data_dir, repository).execute(
            AuthenticatedPrincipal(user=user, token_version=0),
            password="password123",
            confirmation="DELETE",
        )

    assert raised.value.code == "ACCOUNT_DELETE_FAILED"
    assert marker.read_text(encoding="utf-8") == "untouched"
    assert repository.get_by_id(user.user_id) == user


def test_password_lookup_io_failure_is_sanitized_before_any_mutation():
    data_dir = make_data_dir()
    repository = FileIdentityRepository(data_dir)
    user = repository.register("lookup-failure", None, None, "password123", "Lookup Failure")
    user_root = data_dir / "users" / user.user_id
    user_root.mkdir(parents=True)
    marker = user_root / "record.json"
    marker.write_text("untouched", encoding="utf-8")

    with pytest.raises(ApplicationError) as raised:
        DeleteAccount(data_dir, FailingPasswordLookupRepository()).execute(
            AuthenticatedPrincipal(user=user, token_version=0),
            password="password123",
            confirmation="DELETE",
        )

    assert raised.value.code == "ACCOUNT_DELETE_FAILED"
    assert "identity read" not in str(raised.value)
    assert marker.read_text(encoding="utf-8") == "untouched"


def test_storage_cleanup_failure_preserves_identity_password_and_token(monkeypatch):
    data_dir = make_data_dir()
    repository = FileIdentityRepository(data_dir)
    user = repository.register("cleanup-failure", None, None, "password123", "Cleanup Failure")
    user_root = data_dir / "users" / user.user_id
    user_root.mkdir(parents=True)
    assert repository.rotate_token_version(user.user_id) == 1

    def fail_cleanup(_path: Path) -> None:
        raise PermissionError("private filesystem detail")

    monkeypatch.setattr(delete_module.shutil, "rmtree", fail_cleanup)

    with pytest.raises(ApplicationError) as raised:
        DeleteAccount(data_dir, repository).execute(
            AuthenticatedPrincipal(user=user, token_version=1),
            password="password123",
            confirmation="DELETE",
        )

    assert raised.value.code == "ACCOUNT_DELETE_FAILED"
    assert raised.value.message == "Account could not be deleted. Please try again."
    assert "filesystem" not in str(raised.value)
    assert repository.get_by_id(user.user_id) == user
    assert repository.verify_user_password(user.user_id, "password123") is True
    assert repository.get_token_version(user.user_id) == 1


def test_identity_delete_failure_is_stable_and_preserves_atomic_identity(monkeypatch):
    data_dir = make_data_dir()
    repository = FileIdentityRepository(data_dir)
    user = repository.register("identity-failure", None, None, "password123", "Identity Failure")
    user_root = data_dir / "users" / user.user_id
    user_root.mkdir(parents=True)
    users_path = data_dir / "users.json"
    identity_before = users_path.read_bytes()

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("private identity replacement detail")

    monkeypatch.setattr(repository, "replace_file", fail_replace)

    with pytest.raises(ApplicationError) as raised:
        DeleteAccount(data_dir, repository).execute(
            AuthenticatedPrincipal(user=user, token_version=0),
            password="password123",
            confirmation="DELETE",
        )

    assert raised.value.code == "ACCOUNT_DELETE_FAILED"
    assert "replacement" not in str(raised.value)
    assert users_path.read_bytes() == identity_before
    assert repository.get_by_id(user.user_id) == user
    assert repository.get_token_version(user.user_id) == 0
    assert list(data_dir.glob("users.json.*.tmp")) == []
    assert not user_root.exists()

    monkeypatch.undo()
    DeleteAccount(data_dir, repository).execute(
        AuthenticatedPrincipal(user=user, token_version=0),
        password="password123",
        confirmation="DELETE",
    )

    assert repository.get_by_id(user.user_id) is None
