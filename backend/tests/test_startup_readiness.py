from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.api import health
from backend.config import get_settings
from backend.infrastructure import startup
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS
from backend.main import create_app


def test_startup_orders_schema_catalogs_then_per_user_cutover(tmp_path, monkeypatch, caplog):
    events = []
    monkeypatch.setattr(startup, "run_migrations", lambda *_: events.append("schema"))
    monkeypatch.setattr(startup, "_source_identity", lambda _path: ("v1", "a" * 64))
    result = SimpleNamespace(
        skipped=False, inserted_count=1, updated_count=0,
        unchanged_count=0, deactivated_count=0,
    )
    monkeypatch.setattr(
        startup, "seed_bundled_foods",
        lambda *_: events.append("foods") or result,
    )
    monkeypatch.setattr(
        startup, "seed_bundled_exercises",
        lambda *_: events.append("exercises") or result,
    )
    monkeypatch.setattr(
        startup,
        "retire_public_sources",
        lambda *_args, **_kwargs: events.append("retirement")
        or {"status": "completed", "deactivated_count": 0},
    )
    monkeypatch.setattr(startup, "_registered_user_ids", lambda _path: ("user-a",))

    class Migrator:
        def __init__(self, *_args):
            pass

        def migrate_user(self, user_id):
            events.append(f"legacy:{user_id}")
            return SimpleNamespace(
                status="completed", meal_rows=1, meal_groups=1,
                workout_rows=1, backup_checksum="b" * 64,
            )

    monkeypatch.setattr(startup, "LegacyCsvMigrator", Migrator)
    with caplog.at_level("INFO", logger="fitlife.startup"):
        summary = startup.run_startup(SQLiteDatabase(tmp_path / "unused.db"), tmp_path)

    assert events == ["schema", "foods", "retirement", "exercises", "legacy:user-a"]
    assert summary.status == "ready"
    payloads = [json.loads(record.message) for record in caplog.records]
    assert all(
        set(payload) == {
            "operation", "version", "status", "counts", "duration_ms",
            "checksum_prefix",
        }
        for payload in payloads
    )
    serialized = json.dumps(payloads)
    assert "user-a" not in serialized
    assert "api_key" not in serialized.casefold()


def test_recoverable_legacy_failure_serves_degraded_readiness(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    database_path = data_dir / "fitlife.sqlite3"
    data_dir.mkdir(parents=True)
    (data_dir / "users.json").write_text(
        json.dumps([{"user_id": "c" * 32}]), encoding="utf-8"
    )
    user_root = data_dir / "users" / ("c" * 32)
    user_root.mkdir(parents=True)
    (user_root / "meals.csv").write_text("bad,headers\n1,2\n", encoding="utf-8")
    (user_root / "workouts.csv").write_text(
        "date,type,exercise,muscle_group,sets,reps,weight,duration_min\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(database_path))
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "degraded"
        assert response.json()["data"]["failed_legacy_migrations"] == 1
    finally:
        get_settings.cache_clear()


def test_readiness_returns_503_when_database_is_unavailable(monkeypatch):
    class BrokenDatabase:
        def connection(self):
            raise sqlite3.OperationalError("private database path")

    monkeypatch.setattr(health, "get_database", lambda: BrokenDatabase())
    client = TestClient(create_app())

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["data"]["status"] == "unavailable"
    assert "private database path" not in response.text


def test_compose_health_contract_uses_configurable_ports_and_dependency():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "${BACKEND_PORT:-8000}:8000" in compose
    assert "${FRONTEND_PORT:-3000}:80" in compose
    assert "/health/ready" in compose
    assert "condition: service_healthy" in compose
    assert "./backend/data:/app/backend/data" in compose


def test_backend_build_uses_configurable_pip_network_settings():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = Path("backend/Dockerfile").read_text(encoding="utf-8")
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert "PIP_INDEX_URL: ${PIP_INDEX_URL:-https://pypi.org/simple}" in compose
    assert "PIP_DEFAULT_TIMEOUT: ${PIP_DEFAULT_TIMEOUT:-120}" in compose
    assert "PIP_RETRIES: ${PIP_RETRIES:-5}" in compose
    assert "ARG PIP_INDEX_URL=https://pypi.org/simple" in dockerfile
    assert "ARG PIP_DEFAULT_TIMEOUT=120" in dockerfile
    assert "ARG PIP_RETRIES=5" in dockerfile
    assert '--index-url "$PIP_INDEX_URL"' in dockerfile
    assert '--timeout "$PIP_DEFAULT_TIMEOUT"' in dockerfile
    assert '--retries "$PIP_RETRIES"' in dockerfile
    assert "PIP_INDEX_URL=https://pypi.org/simple" in env_example
    assert "PIP_DEFAULT_TIMEOUT=120" in env_example
    assert "PIP_RETRIES=5" in env_example
