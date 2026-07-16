from __future__ import annotations

from pathlib import Path
import shutil
import threading
from uuid import uuid4

import pytest

import backend.application.use_cases.delete_account as delete_module
from backend.application.use_cases.delete_account import DeleteAccount
from backend.config import get_settings
from backend.domain.errors import ApplicationError
from backend.infrastructure.auth.file_identity_repository import FileIdentityRepository
from backend.schemas import AuthenticatedPrincipal
from backend.tools.data_access import DEFAULT_PROFILE, write_profile


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

    def confirm_and_delete_account(
        self,
        user_id: str,
        expected_token_version: int,
        password: str,
        cleanup,
    ):
        result = super().confirm_and_delete_account(
            user_id,
            expected_token_version,
            password,
            cleanup,
        )
        if result == "deleted":
            self.events.append("identity_deleted")
        return result


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

    def confirm_and_delete_account(
        self,
        user_id: str,
        expected_token_version: int,
        password: str,
        cleanup,
    ):
        raise PermissionError("private identity read detail")


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

    assert events == ["storage_deleted", "identity_deleted"]
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


def test_user_root_is_atomically_quarantined_before_recursive_cleanup(monkeypatch):
    data_dir = make_data_dir()
    repository = FileIdentityRepository(data_dir)
    user = repository.register("quarantine-user", None, None, "password123", "Quarantine")
    other = repository.register("quarantine-other", None, None, "password456", "Other")
    user_root = data_dir / "users" / user.user_id
    other_root = data_dir / "users" / other.user_id
    user_root.mkdir(parents=True)
    other_root.mkdir(parents=True)
    (user_root / "record.json").write_text("private", encoding="utf-8")
    other_marker = other_root / "record.json"
    other_marker.write_text("untouched", encoding="utf-8")
    removed_paths: list[Path] = []
    real_rmtree = shutil.rmtree

    def track_quarantine_cleanup(path: Path) -> None:
        removed_paths.append(path)
        real_rmtree(path)

    monkeypatch.setattr(delete_module.shutil, "rmtree", track_quarantine_cleanup)

    DeleteAccount(data_dir, repository).execute(
        AuthenticatedPrincipal(user=user, token_version=0),
        password="password123",
        confirmation="DELETE",
    )

    assert len(removed_paths) == 1
    quarantine = removed_paths[0]
    assert quarantine.parent == user_root.parent
    assert quarantine.name.startswith(f".delete-{user.user_id}-")
    assert quarantine.name.endswith(".quarantine")
    assert not user_root.exists()
    assert not quarantine.exists()
    assert other_marker.read_text(encoding="utf-8") == "untouched"


def test_swapped_quarantine_link_is_never_recursively_followed(monkeypatch):
    data_dir = make_data_dir()
    repository = FileIdentityRepository(data_dir)
    user = repository.register("swap-user", None, None, "password123", "Swap User")
    other = repository.register("swap-other", None, None, "password456", "Swap Other")
    user_root = data_dir / "users" / user.user_id
    other_root = data_dir / "users" / other.user_id
    outside = data_dir / "outside"
    user_root.mkdir(parents=True)
    other_root.mkdir(parents=True)
    outside.mkdir(parents=True)
    (user_root / "record.json").write_text("private", encoding="utf-8")
    other_marker = other_root / "record.json"
    outside_marker = outside / "record.json"
    other_marker.write_text("untouched", encoding="utf-8")
    outside_marker.write_text("untouched", encoding="utf-8")
    real_replace = delete_module.os.replace
    real_rmtree = shutil.rmtree
    quarantine_paths: list[Path] = []
    swapped = False

    def swap_after_rename(source: Path, destination: Path) -> None:
        nonlocal swapped
        real_replace(source, destination)
        quarantine_paths.append(destination)
        swapped = True

    def report_swapped_entry(path: Path) -> bool:
        return swapped and path in quarantine_paths

    def safely_unlink_simulated_reparse(path: Path) -> None:
        assert path in quarantine_paths
        real_rmtree(path)

    def reject_recursive_cleanup(_path: Path) -> None:
        raise AssertionError("untrusted quarantine must not reach rmtree")

    monkeypatch.setattr(delete_module.os, "replace", swap_after_rename)
    monkeypatch.setattr(
        delete_module,
        "_entry_is_link_or_reparse",
        report_swapped_entry,
        raising=False,
    )
    monkeypatch.setattr(
        delete_module,
        "_unlink_reparse_entry",
        safely_unlink_simulated_reparse,
        raising=False,
    )
    monkeypatch.setattr(delete_module.shutil, "rmtree", reject_recursive_cleanup)

    with pytest.raises(ApplicationError) as raised:
        DeleteAccount(data_dir, repository).execute(
            AuthenticatedPrincipal(user=user, token_version=0),
            password="password123",
            confirmation="DELETE",
        )

    assert raised.value.code == "ACCOUNT_DELETE_FAILED"
    assert outside_marker.read_text(encoding="utf-8") == "untouched"
    assert other_marker.read_text(encoding="utf-8") == "untouched"
    assert repository.get_by_id(user.user_id) == user
    assert quarantine_paths and not quarantine_paths[0].exists()


def test_nested_file_disappearance_keeps_identity_while_quarantine_remains(monkeypatch):
    data_dir = make_data_dir()
    repository = FileIdentityRepository(data_dir)
    user = repository.register("nested-missing", None, None, "password123", "Nested Missing")
    user_root = data_dir / "users" / user.user_id
    nested = user_root / "nested"
    nested.mkdir(parents=True)
    (nested / "record.json").write_text("private", encoding="utf-8")
    quarantine_paths: list[Path] = []

    def fail_after_nested_disappearance(path: Path) -> None:
        quarantine_paths.append(path)
        (path / "nested" / "record.json").unlink()
        raise FileNotFoundError("nested entry disappeared")

    monkeypatch.setattr(delete_module.shutil, "rmtree", fail_after_nested_disappearance)

    with pytest.raises(ApplicationError) as raised:
        DeleteAccount(data_dir, repository).execute(
            AuthenticatedPrincipal(user=user, token_version=0),
            password="password123",
            confirmation="DELETE",
        )

    assert raised.value.code == "ACCOUNT_DELETE_FAILED"
    assert repository.get_by_id(user.user_id) == user
    assert not user_root.exists()
    assert quarantine_paths and quarantine_paths[0].exists()

    monkeypatch.undo()
    DeleteAccount(data_dir, repository).execute(
        AuthenticatedPrincipal(user=user, token_version=0),
        password="password123",
        confirmation="DELETE",
    )

    assert repository.get_by_id(user.user_id) is None
    assert not quarantine_paths[0].exists()


def test_stale_principal_is_rejected_before_storage_cleanup():
    data_dir = make_data_dir()
    events: list[str] = []
    repository = TrackingIdentityRepository(data_dir, events)
    user = repository.register("stale-delete", None, None, "password123", "Stale Delete")
    user_root = data_dir / "users" / user.user_id
    user_root.mkdir(parents=True)
    marker = user_root / "record.json"
    marker.write_text("untouched", encoding="utf-8")
    assert repository.rotate_token_version(user.user_id) == 1

    with pytest.raises(ApplicationError) as raised:
        DeleteAccount(data_dir, repository).execute(
            AuthenticatedPrincipal(user=user, token_version=0),
            password="password123",
            confirmation="DELETE",
        )

    assert raised.value.code == "AUTH_TOKEN_INVALID"
    assert events == []
    assert marker.read_text(encoding="utf-8") == "untouched"
    assert repository.get_by_id(user.user_id) == user
    assert repository.get_token_version(user.user_id) == 1


def test_authenticated_writer_cannot_recreate_user_data_after_deletion(monkeypatch):
    data_dir = make_data_dir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    repository = FileIdentityRepository(data_dir)
    user = repository.register("racing-writer", None, None, "password123", "Racing Writer")
    user_root = data_dir / "users" / user.user_id
    user_root.mkdir(parents=True)
    (user_root / "record.json").write_text("private", encoding="utf-8")
    storage_removed = threading.Event()
    release_deletion = threading.Event()
    writer_started = threading.Event()
    writer_errors: list[Exception] = []
    real_rmtree = shutil.rmtree

    def pause_after_storage_cleanup(path: Path) -> None:
        real_rmtree(path)
        storage_removed.set()
        assert release_deletion.wait(timeout=5)

    monkeypatch.setattr(delete_module.shutil, "rmtree", pause_after_storage_cleanup)

    deletion = threading.Thread(
        target=lambda: DeleteAccount(data_dir, repository).execute(
            AuthenticatedPrincipal(user=user, token_version=0),
            password="password123",
            confirmation="DELETE",
        )
    )

    def write_after_authentication() -> None:
        writer_started.set()
        try:
            write_profile(DEFAULT_PROFILE, user.user_id)
        except Exception as error:
            writer_errors.append(error)

    deletion.start()
    assert storage_removed.wait(timeout=5)
    writer = threading.Thread(target=write_after_authentication)
    writer.start()
    assert writer_started.wait(timeout=5)
    release_deletion.set()
    deletion.join(timeout=5)
    writer.join(timeout=5)
    get_settings.cache_clear()

    assert not deletion.is_alive()
    assert not writer.is_alive()
    assert len(writer_errors) == 1
    assert isinstance(writer_errors[0], ApplicationError)
    assert writer_errors[0].code == "AUTH_TOKEN_INVALID"
    assert not user_root.exists()


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
            [],
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


def test_account_deletion_rejects_reparse_users_root(monkeypatch):
    data_dir = make_data_dir()
    repository = FileIdentityRepository(data_dir)
    user = repository.register("junction-root", None, None, "password123", "Junction Root")
    users_root = data_dir / "users"
    user_root = users_root / user.user_id
    user_root.mkdir(parents=True)
    marker = user_root / "record.json"
    marker.write_text("untouched", encoding="utf-8")
    real_check = delete_module._entry_is_link_or_reparse

    def report_users_root_as_reparse(path: Path) -> bool:
        return path == users_root or real_check(path)

    monkeypatch.setattr(
        delete_module,
        "_entry_is_link_or_reparse",
        report_users_root_as_reparse,
    )

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
