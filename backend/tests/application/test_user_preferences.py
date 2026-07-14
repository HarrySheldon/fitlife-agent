import json
from pathlib import Path
from uuid import uuid4

import pytest

from backend.application.use_cases.user_preferences import GetUserPreferences, UpdateUserPreferences
from backend.domain.user_preferences import UserPreferences
from backend.infrastructure.settings.file_user_preferences_repository import FileUserPreferencesRepository


def make_data_dir() -> Path:
    return Path(".tmp") / "pytest-user-preferences" / uuid4().hex


def test_preferences_initialize_from_valid_request_hints_once():
    repository = FileUserPreferencesRepository(make_data_dir())

    created = GetUserPreferences(repository).execute(
        "user-a",
        language_hint="zh-CN,zh;q=0.9",
        timezone_hint="Asia/Shanghai",
    )
    fetched = GetUserPreferences(repository).execute(
        "user-a",
        language_hint="en-US",
        timezone_hint="America/New_York",
    )

    assert created == UserPreferences(language="zh-CN", unit_system="metric", timezone="Asia/Shanghai")
    assert fetched == created


def test_preferences_update_is_partial_and_isolated_by_user():
    repository = FileUserPreferencesRepository(make_data_dir())
    GetUserPreferences(repository).execute("user-a", timezone_hint="UTC")

    updated = UpdateUserPreferences(repository).execute("user-a", unit_system="imperial")
    other = GetUserPreferences(repository).execute("user-b", timezone_hint="Europe/London")

    assert updated.language == "en-US"
    assert updated.unit_system == "imperial"
    assert updated.timezone == "UTC"
    assert other == UserPreferences(timezone="Europe/London")


def test_preferences_reject_invalid_iana_timezone():
    with pytest.raises(ValueError, match="IANA timezone"):
        UserPreferences(timezone="GMT+8")


def test_preferences_repository_uses_atomic_replacement(monkeypatch):
    data_dir = make_data_dir()
    repository = FileUserPreferencesRepository(data_dir)
    replacements: list[tuple[Path, Path]] = []
    real_replace = repository.replace_file
    monkeypatch.setattr(
        repository,
        "replace_file",
        lambda source, destination: (replacements.append((source, destination)), real_replace(source, destination))[1],
    )

    repository.save("user-a", UserPreferences(language="zh-CN", timezone="Asia/Shanghai"))

    assert len(replacements) == 1
    assert replacements[0][1].name == "preferences.json"
    payload = json.loads((data_dir / "users" / "user-a" / "preferences.json").read_text(encoding="utf-8"))
    assert payload == {"language": "zh-CN", "unit_system": "metric", "timezone": "Asia/Shanghai"}

