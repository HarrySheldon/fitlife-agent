import pandas as pd

from backend.application.ports.fitness_repository import FitnessRepository
from backend.infrastructure.repositories.file_fitness_repository import FileFitnessRepository
from backend.schemas import MealRecord
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
