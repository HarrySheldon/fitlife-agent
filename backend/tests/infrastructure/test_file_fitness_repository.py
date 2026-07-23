from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace

import pandas as pd

from backend.application.ports.fitness_repository import FitnessRepository
from backend.application.use_cases.profile_targets import FileLegacyProfileProjection
from backend.config import get_settings
from backend.infrastructure.repositories.file_fitness_repository import FileFitnessRepository
from backend.schemas import MealRecord, UserProfile
from backend.tools import data_access


def test_file_repository_preserves_user_scope(monkeypatch):
    stored: dict[str, list[dict]] = {"user-a": [], "user-b": []}

    def append_meal(record, user_id):
        stored[user_id].append(record.model_dump())

    def read_meals(user_id):
        return pd.DataFrame(stored[user_id], columns=data_access.MEAL_COLUMNS)

    monkeypatch.setattr(data_access, "append_meal", append_meal)
    monkeypatch.setattr(data_access, "read_meals", read_meals)
    repository = FileFitnessRepository()
    repository.append_meal(
        MealRecord(
            date="2026-07-13",
            meal="lunch",
            food="rice and tofu",
            amount="1 serving",
            calories=520,
            protein=28,
            carbs=70,
            fat=14,
        ),
        "user-a",
    )

    assert isinstance(repository, FitnessRepository)
    assert len(repository.read_meals("user-a")) == 1
    assert repository.read_meals("user-b").empty


def test_atomic_profile_update_serializes_concurrent_read_modify_write(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    repository = FileFitnessRepository()
    user_id = "atomic-profile-user"
    repository.write_profile(
        UserProfile(
            height_cm=175,
            weight_kg=70,
            age=30,
            gender="male",
            goal="maintenance",
            weekly_training_frequency=3,
            target_weight_kg=70,
            daily_calorie_target=2200,
            daily_protein_target=120,
        ),
        user_id,
    )
    first_entered = Event()
    release_first = Event()
    second_entered = Event()

    def update_diet(current):
        first_entered.set()
        assert release_first.wait(timeout=5)
        return current.model_copy(update={"diet_preferences": ["vegetarian"]})

    def update_training(current):
        second_entered.set()
        return current.model_copy(update={"training_preference": "strength"})

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(
                repository.update_profile_atomically,
                update_diet,
                user_id,
            )
            assert first_entered.wait(timeout=5)
            second = executor.submit(
                repository.update_profile_atomically,
                update_training,
                user_id,
            )
            assert not second_entered.wait(timeout=0.1)
            release_first.set()
            first.result(timeout=5)
            second.result(timeout=5)

        saved = repository.read_profile(user_id)
        assert saved.diet_preferences == ["vegetarian"]
        assert saved.training_preference == "strength"
        assert isinstance(repository, FitnessRepository)
    finally:
        get_settings.cache_clear()


def test_concurrent_legacy_projection_preserves_unrelated_profile_update(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    repository = FileFitnessRepository()
    user_id = "concurrent-projection-user"
    repository.write_profile(
        UserProfile(
            height_cm=170,
            weight_kg=65,
            age=25,
            gender="other",
            goal="maintenance",
            weekly_training_frequency=3,
            target_weight_kg=60,
            daily_calorie_target=2000,
            daily_protein_target=100,
        ),
        user_id,
    )
    original_update = repository.update_profile_atomically
    first_call_guard = Lock()
    first_call = True
    projection_entered = Event()
    release_projection = Event()
    unrelated_entered = Event()

    def coordinated_update(update, scoped_user_id):
        nonlocal first_call
        with first_call_guard:
            coordinate = first_call
            first_call = False
        if coordinate:
            def delayed(current):
                projection_entered.set()
                assert release_projection.wait(timeout=5)
                return update(current)

            return original_update(delayed, scoped_user_id)
        return original_update(update, scoped_user_id)

    repository.update_profile_atomically = coordinated_update
    projection = FileLegacyProfileProjection(repository)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            projected = executor.submit(
                projection.project,
                user_id,
                SimpleNamespace(height_cm=180, weight_kg=80, age=35),
                SimpleNamespace(goal="muscle_gain"),
                SimpleNamespace(calories=3000, protein=160),
            )
            assert projection_entered.wait(timeout=5)

            def update_unrelated(current):
                unrelated_entered.set()
                return current.model_copy(
                    update={"diet_preferences": ["vegetarian"]}
                )

            unrelated = executor.submit(
                repository.update_profile_atomically,
                update_unrelated,
                user_id,
            )
            assert not unrelated_entered.wait(timeout=0.1)
            release_projection.set()
            projected.result(timeout=5)
            unrelated.result(timeout=5)

        saved = repository.read_profile(user_id)
        assert saved.height_cm == 180
        assert saved.weight_kg == 80
        assert saved.goal == "muscle_gain"
        assert saved.daily_calorie_target == 3000
        assert saved.daily_protein_target == 160
        assert saved.diet_preferences == ["vegetarian"]
    finally:
        get_settings.cache_clear()
