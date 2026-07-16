from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.errors import ApplicationError
from backend.domain.model_connection import ModelConnection
from backend.domain.user_preferences import UserPreferences
from backend.config import get_settings
from backend.infrastructure.settings.file_model_connection_repository import (
    FileModelConnectionRepository,
)
from backend.infrastructure.settings.file_user_preferences_repository import (
    FileUserPreferencesRepository,
)
from backend.infrastructure.user_lifecycle import user_lifecycle_guard
from backend.schemas import MealRecord, WorkoutRecord
from backend.tools.data_access import (
    DEFAULT_PROFILE,
    append_meal,
    append_workout,
    ensure_user_data,
    write_data_bytes,
    write_profile,
)


def make_data_dir() -> Path:
    return Path(".tmp") / "pytest-user-lifecycle" / uuid4().hex


def test_preferences_save_refuses_to_recreate_deleted_user_directory():
    data_dir = make_data_dir()
    user_id = uuid4().hex
    with user_lifecycle_guard(data_dir, user_id) as lifecycle:
        lifecycle.mark_deleted()

    with pytest.raises(ApplicationError) as raised:
        FileUserPreferencesRepository(data_dir).save(user_id, UserPreferences())

    assert raised.value.code == "AUTH_TOKEN_INVALID"
    assert not (data_dir / "users" / user_id).exists()


@pytest.mark.parametrize(
    "mutation",
    ["initialize", "profile", "meal", "workout", "upload", "model", "preferences"],
)
def test_all_per_user_mutations_share_deleted_tombstone(monkeypatch, mutation: str):
    data_dir = make_data_dir()
    user_id = uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    with user_lifecycle_guard(data_dir, user_id) as lifecycle:
        lifecycle.mark_deleted()

    actions = {
        "initialize": lambda: ensure_user_data(user_id),
        "profile": lambda: write_profile(DEFAULT_PROFILE, user_id),
        "meal": lambda: append_meal(
            MealRecord(
                date="2026-07-16",
                meal="lunch",
                food="rice",
                amount="100g",
                calories=100,
                protein=2,
                carbs=20,
                fat=1,
            ),
            user_id,
        ),
        "workout": lambda: append_workout(
            WorkoutRecord(
                date="2026-07-16",
                type="strength",
                exercise="squat",
                muscle_group="legs",
                duration_min=30,
            ),
            user_id,
        ),
        "upload": lambda: write_data_bytes("meals.csv", b"date,meal\n", user_id),
        "model": lambda: FileModelConnectionRepository(data_dir).save(
            user_id, ModelConnection()
        ),
        "preferences": lambda: FileUserPreferencesRepository(data_dir).save(
            user_id, UserPreferences()
        ),
    }

    with pytest.raises(ApplicationError) as raised:
        actions[mutation]()

    get_settings.cache_clear()
    assert raised.value.code == "AUTH_TOKEN_INVALID"
    assert not (data_dir / "users" / user_id).exists()
