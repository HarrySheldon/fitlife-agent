from __future__ import annotations

from pathlib import Path

from backend.config import get_settings
from backend.infrastructure.migration.legacy_csv import LegacyCsvMigrator
from backend.infrastructure.repositories.cutover_fitness_repository import (
    CutoverFitnessRepository,
)
from backend.infrastructure.repositories.file_fitness_repository import FileFitnessRepository
from backend.infrastructure.repositories.sqlite_fitness_repository import SQLiteFitnessRepository
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS
from backend.schemas import MealRecord, WorkoutRecord
from backend.tools.data_access import MEAL_COLUMNS, WORKOUT_COLUMNS


USER = "b" * 32


def _setup(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data))
    get_settings.cache_clear()
    root = data / "users" / USER
    root.mkdir(parents=True)
    (root / "meals.csv").write_text(
        ",".join(MEAL_COLUMNS) + "\n2026-07-01,lunch,rice,100g,116,2.6,25.9,0.3\n",
        encoding="utf-8",
    )
    (root / "workouts.csv").write_text(
        ",".join(WORKOUT_COLUMNS) + "\n2026-07-01,strength,squat,legs,3,8,60,45\n",
        encoding="utf-8",
    )
    database = SQLiteDatabase(data / "fitlife.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    file_repository = FileFitnessRepository()
    sqlite_repository = SQLiteFitnessRepository(
        database, profiles=file_repository, data_dir=data
    )
    return data, root, database, CutoverFitnessRepository(
        database,
        file_repository=file_repository,
        sqlite_repository=sqlite_repository,
    )


def test_failed_or_incomplete_user_stays_file_backed(tmp_path, monkeypatch):
    _, root, database, repository = _setup(tmp_path, monkeypatch)
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO data_migrations (
                migration_key, user_id, checksum, status
            ) VALUES (?, ?, ?, 'failed')
            """,
            (f"legacy_csv_v1:{USER}", USER, "a" * 64),
        )

    repository.append_meal(_meal("file meal"), USER)

    assert list(repository.read_meals(USER)["food"]) == ["rice", "file meal"]
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM meal_items").fetchone()[0] == 0
    assert "file meal" in (root / "meals.csv").read_text(encoding="utf-8")


def test_completed_user_uses_sqlite_and_never_falls_back_on_file_drift(tmp_path, monkeypatch):
    data, root, database, repository = _setup(tmp_path, monkeypatch)
    assert LegacyCsvMigrator(database, data).migrate_user(USER).status == "completed"
    (root / "meals.csv").write_text(
        ",".join(MEAL_COLUMNS) + "\n2026-07-02,dinner,drift,1,999,0,0,0\n",
        encoding="utf-8",
    )

    repository.append_meal(_meal("sqlite meal"), USER)
    repository.append_workout(_workout("deadlift"), USER)

    meals = repository.read_meals(USER)
    workouts = repository.read_workouts(USER)
    assert list(meals["food"]) == ["rice", "sqlite meal"]
    assert "drift" not in set(meals["food"])
    assert list(workouts["exercise"]) == ["squat", "deadlift"]
    assert "sqlite meal" not in (root / "meals.csv").read_text(encoding="utf-8")


def test_signed_in_csv_import_is_atomic_archived_and_idempotent(tmp_path, monkeypatch):
    data, _, database, _ = _setup(tmp_path, monkeypatch)
    sqlite = SQLiteFitnessRepository(database, data_dir=data)
    content = (
        ",".join(MEAL_COLUMNS)
        + "\n2026-07-03,dinner,tofu,200g,288,34.6,5.56,17.44\n"
    ).encode()

    first = sqlite.import_meals_csv(USER, content)
    replay = sqlite.import_meals_csv(USER, content)

    assert first.imported_count == 1
    assert first.replayed is False
    assert replay == type(replay)(0, True, first.checksum)
    assert list(sqlite.read_meals(USER)["food"]) == ["tofu"]
    archives = list((data / "users" / USER / "imports").glob("meals-*.csv"))
    assert len(archives) == 1
    assert archives[0].read_bytes() == content


def _meal(food: str) -> MealRecord:
    return MealRecord(
        date="2026-07-02", meal="dinner", food=food, amount="1 serving",
        calories=400, protein=25, carbs=40, fat=12,
    )


def _workout(exercise: str) -> WorkoutRecord:
    return WorkoutRecord(
        date="2026-07-02", type="strength", exercise=exercise,
        muscle_group="back", sets=4, reps=6, weight=80, duration_min=50,
    )
