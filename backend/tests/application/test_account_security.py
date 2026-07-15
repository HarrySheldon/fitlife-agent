import json
from pathlib import Path
from uuid import uuid4

import pytest

from backend.application.use_cases.account_security import ChangePassword, RevokeOtherSessions
from backend.config import get_settings
from backend.domain.errors import ApplicationError
from backend.infrastructure.auth.file_identity_repository import FileIdentityRepository
from backend.schemas import AuthSession
from backend.tools.auth_store import create_access_token, user_from_token


def make_data_dir() -> Path:
    return Path(".tmp") / "pytest-account-security" / uuid4().hex


def issue_session(user, token_version: int) -> AuthSession:
    return AuthSession(access_token=f"token-version-{token_version}", user=user)


def issue_real_session(user, token_version: int) -> AuthSession:
    return AuthSession(access_token=create_access_token(user, token_version), user=user)


def test_wrong_current_password_leaves_password_hash_and_version_unchanged():
    data_dir = make_data_dir()
    repository = FileIdentityRepository(data_dir)
    user = repository.register("security-user", None, None, "password123", "Security User")
    users_path = data_dir / "users.json"
    before = json.loads(users_path.read_text(encoding="utf-8"))[0]

    with pytest.raises(ApplicationError) as raised:
        ChangePassword(repository, issue_session).execute(
            user,
            current_password="wrong-password",
            new_password="replacement123",
        )

    after = json.loads(users_path.read_text(encoding="utf-8"))[0]
    assert raised.value.code == "ACCOUNT_CURRENT_PASSWORD_INVALID"
    assert after["password_hash"] == before["password_hash"]
    assert after["token_version"] == before["token_version"]


@pytest.mark.parametrize("new_password", ["short7", "x" * 129])
def test_new_password_policy_rejects_lengths_outside_8_to_128(new_password: str):
    data_dir = make_data_dir()
    repository = FileIdentityRepository(data_dir)
    user = repository.register("policy-user", None, None, "password123", "Policy User")
    users_path = data_dir / "users.json"
    before = json.loads(users_path.read_text(encoding="utf-8"))[0]

    with pytest.raises(ApplicationError) as raised:
        ChangePassword(repository, issue_session).execute(
            user,
            current_password="password123",
            new_password=new_password,
        )

    after = json.loads(users_path.read_text(encoding="utf-8"))[0]
    assert raised.value.code == "ACCOUNT_PASSWORD_POLICY"
    assert after["password_hash"] == before["password_hash"]
    assert after["token_version"] == before["token_version"]


def test_new_password_must_differ_from_current_password():
    data_dir = make_data_dir()
    repository = FileIdentityRepository(data_dir)
    user = repository.register("unchanged-user", None, None, "password123", "Unchanged User")
    users_path = data_dir / "users.json"
    before = json.loads(users_path.read_text(encoding="utf-8"))[0]

    with pytest.raises(ApplicationError) as raised:
        ChangePassword(repository, issue_session).execute(
            user,
            current_password="password123",
            new_password="password123",
        )

    after = json.loads(users_path.read_text(encoding="utf-8"))[0]
    assert raised.value.code == "ACCOUNT_PASSWORD_UNCHANGED"
    assert after["password_hash"] == before["password_hash"]
    assert after["token_version"] == before["token_version"]


def test_successful_password_change_rotates_credentials_and_returns_valid_replacement_session(
    monkeypatch,
):
    data_dir = make_data_dir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    repository = FileIdentityRepository(data_dir)
    user = repository.register("changed-user", None, None, "password123", "Changed User")
    old_token = create_access_token(user)

    replacement = ChangePassword(repository, issue_real_session).execute(
        user,
        current_password="password123",
        new_password="replacement123",
    )

    assert repository.authenticate("changed-user", "password123") is None
    assert repository.authenticate("changed-user", "replacement123") == user
    assert repository.get_token_version(user.user_id) == 1
    assert user_from_token(old_token) is None
    assert user_from_token(replacement.access_token) == user
    get_settings.cache_clear()


def test_revoke_other_sessions_rotates_only_current_users_version_and_keeps_password(
    monkeypatch,
):
    data_dir = make_data_dir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    repository = FileIdentityRepository(data_dir)
    user = repository.register("revoked-user", None, None, "password123", "Revoked User")
    other = repository.register("other-user", None, None, "password456", "Other User")
    old_token = create_access_token(user)
    other_token = create_access_token(other)
    users_path = data_dir / "users.json"
    password_hash = json.loads(users_path.read_text(encoding="utf-8"))[0]["password_hash"]

    replacement = RevokeOtherSessions(repository, issue_real_session).execute(user)

    stored_users = json.loads(users_path.read_text(encoding="utf-8"))
    stored_user = next(item for item in stored_users if item["user_id"] == user.user_id)
    assert stored_user["password_hash"] == password_hash
    assert repository.authenticate("revoked-user", "password123") == user
    assert user_from_token(old_token) is None
    assert user_from_token(replacement.access_token) == user
    assert user_from_token(other_token) == other
    get_settings.cache_clear()


def test_password_change_write_failure_preserves_password_and_token_version(monkeypatch):
    data_dir = make_data_dir()
    repository = FileIdentityRepository(data_dir)
    user = repository.register("write-failure-user", None, None, "password123", "Write Failure")
    users_path = data_dir / "users.json"
    before = json.loads(users_path.read_text(encoding="utf-8"))[0]

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(repository, "replace_file", fail_replace)

    with pytest.raises(OSError, match="simulated replacement failure"):
        ChangePassword(repository, issue_session).execute(
            user,
            current_password="password123",
            new_password="replacement123",
        )

    after = json.loads(users_path.read_text(encoding="utf-8"))[0]
    assert after["password_hash"] == before["password_hash"]
    assert after["token_version"] == before["token_version"]
    assert repository.authenticate("write-failure-user", "password123") == user
    assert repository.authenticate("write-failure-user", "replacement123") is None
