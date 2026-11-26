import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.infrastructure import startup as startup_module
from backend.infrastructure.postgres.runtime import get_database
from backend.main import create_app
from backend.tools.data_access import (
    DEFAULT_PROFILE,
    MEAL_COLUMNS,
    WORKOUT_COLUMNS,
    write_data_bytes,
    write_profile,
)


@pytest.fixture
def isolated_runtime(tmp_path, monkeypatch, make_isolated_pg_db):
    data_dir = tmp_path / "data"
    database = make_isolated_pg_db(initialize=False)

    with monkeypatch.context() as environment:
        environment.setenv("DATA_DIR", str(data_dir))
        environment.setenv("DATABASE_URL", database.dsn)
        environment.setenv("DATABASE_SCHEMA", database.target_schema)
        get_settings.cache_clear()
        try:
            write_profile(DEFAULT_PROFILE)
            write_data_bytes(
                "meals.csv", (",".join(MEAL_COLUMNS) + "\n").encode("utf-8")
            )
            write_data_bytes(
                "workouts.csv", (",".join(WORKOUT_COLUMNS) + "\n").encode("utf-8")
            )
            yield data_dir, database
        finally:
            get_settings.cache_clear()


def test_startup_initializes_database_without_breaking_csv_reads(isolated_runtime):
    data_dir, database = isolated_runtime
    application = create_app()

    with database.connection() as connection:
        before_table = connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = 'schema_migrations'"
        ).fetchone()
    assert before_table is None

    with TestClient(application) as client:
        with database.connection() as connection:
            during_table = connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = 'schema_migrations'"
            ).fetchone()
        assert during_table is not None
        health = client.get("/health")
        readiness = client.get("/health/ready")
        dashboard = client.get("/dashboard/summary")

    assert health.status_code == 200
    assert health.json()["success"] is True
    assert readiness.status_code == 200
    assert readiness.json()["data"]["status"] == "ready"
    assert readiness.json()["data"]["database"] == "ok"
    assert dashboard.status_code == 200
    assert dashboard.json()["success"] is True
    assert dashboard.json()["processing_mode"] == "deterministic"
    assert (data_dir / "meals.csv").read_text(encoding="utf-8").splitlines() == [
        ",".join(MEAL_COLUMNS)
    ]
    assert (data_dir / "workouts.csv").read_text(encoding="utf-8").splitlines() == [
        ",".join(WORKOUT_COLUMNS)
    ]

    with database.connection() as connection:
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert [version for version, in versions] == list(range(1, 17))


def test_registration_after_startup_immediately_cuts_over_empty_user(isolated_runtime):
    _, database = isolated_runtime
    with TestClient(create_app()) as client:
        registered = client.post(
            "/auth/register",
            json={
                "username": "post-startup-user",
                "password": "password123",
                "display_name": "Post Startup",
            },
        )

    assert registered.status_code == 200
    user_id = registered.json()["data"]["user"]["user_id"]
    with database.connection() as connection:
        row = connection.execute(
            "SELECT status FROM data_migrations WHERE migration_key = ? AND user_id = ?",
            (f"legacy_csv_v1:{user_id}", user_id),
        ).fetchone()
    assert row is not None
    assert row["status"] == "completed"


def test_startup_validates_the_safety_packs(isolated_runtime):
    """The rule packs are validated at boot, not on the first request that needs them."""
    _, _ = isolated_runtime
    summary = startup_module.run_startup()

    assert summary.status == "ready"


def test_startup_refuses_to_run_with_a_broken_safety_pack(isolated_runtime, monkeypatch):
    """A broken pack must refuse to start rather than weaken the gate at runtime."""
    _, _ = isolated_runtime

    def broken_pack():
        raise ValueError("policy references an unknown concern: nope")

    monkeypatch.setattr(startup_module, "load_safety_packs", broken_pack)

    with pytest.raises(ValueError):
        startup_module.run_startup()


def test_startup_interrupts_turns_a_restart_cannot_resume(isolated_runtime):
    """A new process owns no inference: saying so beats pretending it still runs."""
    _, database = isolated_runtime
    startup_module.run_startup()

    from datetime import datetime, timezone

    from backend.infrastructure.repositories.postgres_coach_conversation_repository import (
        PostgresCoachConversationRepository,
    )

    repository = PostgresCoachConversationRepository(database)
    now = datetime.now(timezone.utc)
    repository.create_conversation(
        "alice", conversation_id="c1", title="Today", created_at=now
    )
    repository.accept_turn(
        "alice",
        "c1",
        turn_id="t1",
        idempotency_key="k1",
        request_fingerprint="fp",
        created_at=now,
    )
    repository.claim_turn("alice", "t1", lease_id="worker-before-restart", started_at=now)

    startup_module.run_startup()

    turn = repository.get_turn("alice", "t1")
    assert turn.status == "interrupted"
    assert turn.error_code is None
    assert repository.active_turn("alice") is None
