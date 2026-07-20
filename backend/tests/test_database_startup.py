import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app


@pytest.fixture
def database_path(tmp_path, monkeypatch):
    path = tmp_path / "fitlife.sqlite3"

    with monkeypatch.context() as environment:
        environment.setenv("SQLITE_DATABASE_PATH", str(path))
        get_settings.cache_clear()
        try:
            yield path
        finally:
            get_settings.cache_clear()


def test_startup_initializes_records_database(database_path):
    application = create_app()

    assert not database_path.exists()

    with TestClient(application) as client:
        response = client.get("/health")

    assert database_path.exists()
    assert response.status_code == 200

    with sqlite3.connect(database_path) as connection:
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert [version for version, in versions] == [1]
