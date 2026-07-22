import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app
from backend.tools.data_access import (
    DEFAULT_PROFILE,
    MEAL_COLUMNS,
    WORKOUT_COLUMNS,
    write_data_bytes,
    write_profile,
)


@pytest.fixture
def isolated_runtime(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    path = tmp_path / "fitlife.sqlite3"

    with monkeypatch.context() as environment:
        environment.setenv("DATA_DIR", str(data_dir))
        environment.setenv("SQLITE_DATABASE_PATH", str(path))
        get_settings.cache_clear()
        try:
            write_profile(DEFAULT_PROFILE)
            write_data_bytes(
                "meals.csv", (",".join(MEAL_COLUMNS) + "\n").encode("utf-8")
            )
            write_data_bytes(
                "workouts.csv", (",".join(WORKOUT_COLUMNS) + "\n").encode("utf-8")
            )
            yield data_dir, path
        finally:
            get_settings.cache_clear()


def test_startup_initializes_database_without_breaking_csv_reads(isolated_runtime):
    data_dir, database_path = isolated_runtime
    application = create_app()

    assert not database_path.exists()

    with TestClient(application) as client:
        assert database_path.exists()
        health = client.get("/health")
        dashboard = client.get("/dashboard/summary")

    assert database_path.exists()
    assert health.status_code == 200
    assert health.json()["success"] is True
    assert dashboard.status_code == 200
    assert dashboard.json()["success"] is True
    assert dashboard.json()["processing_mode"] == "deterministic"
    assert (data_dir / "meals.csv").read_text(encoding="utf-8").splitlines() == [
        ",".join(MEAL_COLUMNS)
    ]
    assert (data_dir / "workouts.csv").read_text(encoding="utf-8").splitlines() == [
        ",".join(WORKOUT_COLUMNS)
    ]

    with sqlite3.connect(database_path) as connection:
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert [version for version, in versions] == [1, 2]
