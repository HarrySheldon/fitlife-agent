"""One source per deployment, and the switch refuses to guess.

The failure these tests are built around is quiet: a deployment that turns on
``sqlite`` before importing serves every user an empty plan history while the
files sit on disk. Nothing errors, nothing logs, and the UI shows "no plans".
So the refusal has to happen at construction time, not on the first read.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.config import Settings
from backend.domain.errors import ApplicationError
from backend.infrastructure.repositories.file_plan_repository import FilePlanRepository
from backend.infrastructure.repositories.plan_repository_factory import (
    build_plan_activation_repository,
    build_plan_repository,
    require_imported,
)
from backend.infrastructure.postgres.database import PostgresDatabase
from backend.infrastructure.repositories.postgres_plan_repository import (
    PostgresPlanRepository,
)
from backend.tests.conftest import TEST_DATABASE_URL

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)


def _settings(tmp_path, mode="file", database: PostgresDatabase | None = None):
    return Settings(
        data_dir=tmp_path / "data",
        plan_storage_mode=mode,
        database_url=database.dsn if database is not None else Settings().database_url,
        database_schema=database.target_schema if database is not None else "public",
    )


def _record_import(database, data_dir, *, owners=1, plans=2):
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO plan_import_state (id, data_dir, completed_at, owner_count,"
            " plan_count, draft_count) VALUES (1, ?, ?, ?, ?, 0)"
            " ON CONFLICT(id) DO UPDATE SET data_dir=excluded.data_dir,"
            " owner_count=excluded.owner_count, plan_count=excluded.plan_count",
            (str(data_dir.resolve()), NOW.isoformat(), owners, plans))


def test_the_default_mode_is_the_file_store(tmp_path):
    repository = build_plan_repository(_settings(tmp_path))

    assert isinstance(repository, FilePlanRepository)


def test_file_mode_never_opens_the_database(tmp_path):
    schema = f"test_unopened_{uuid4().hex[:12]}"
    database = PostgresDatabase(TEST_DATABASE_URL, schema=schema)
    settings = _settings(tmp_path, "file", database)
    build_plan_repository(settings)

    with PostgresDatabase(TEST_DATABASE_URL).connection() as connection:
        row = connection.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = ?",
            (schema,),
        ).fetchone()
    assert row is None


def test_postgres_mode_without_an_import_is_refused(tmp_path, pg_db):
    with pytest.raises(ApplicationError) as raised:
        build_plan_repository(_settings(tmp_path, "postgres", pg_db), database=pg_db)

    assert raised.value.code == "CONFIGURATION_INVALID"
    assert "import" in raised.value.message


def test_an_import_of_a_different_directory_is_refused(tmp_path, pg_db):
    database = pg_db
    _record_import(database, tmp_path / "somewhere-else")

    with pytest.raises(ApplicationError) as raised:
        build_plan_repository(_settings(tmp_path, "postgres", database), database=database)

    assert raised.value.code == "CONFIGURATION_INVALID"


def test_postgres_mode_with_a_matching_import_returns_the_postgres_store(tmp_path, pg_db):
    database = pg_db
    settings = _settings(tmp_path, "postgres", database)
    _record_import(database, settings.data_dir)

    repository = build_plan_repository(settings, database=database)

    assert isinstance(repository, PostgresPlanRepository)


def test_a_file_store_cannot_confirm(tmp_path):
    with pytest.raises(ApplicationError) as raised:
        build_plan_activation_repository(_settings(tmp_path))

    assert raised.value.code == "CONFIGURATION_INVALID"


def test_a_postgres_store_can_confirm(tmp_path, pg_db):
    database = pg_db
    settings = _settings(tmp_path, "postgres", database)
    _record_import(database, settings.data_dir)

    assert hasattr(build_plan_activation_repository(settings, database=database),
                   "activate")


def test_an_unknown_mode_is_a_configuration_error(tmp_path):
    settings = _settings(tmp_path)
    object.__setattr__(settings, "plan_storage_mode", "invalid_mode")

    with pytest.raises(ApplicationError) as raised:
        build_plan_repository(settings)

    assert raised.value.code == "CONFIGURATION_INVALID"


def test_the_import_record_reports_what_it_covered(tmp_path, pg_db):
    database = pg_db
    settings = _settings(tmp_path, "postgres", database)
    _record_import(database, settings.data_dir, owners=3, plans=7)

    state = require_imported(settings, database)

    assert state["owner_count"] == 3 and state["plan_count"] == 7


def test_the_factory_opens_the_database_the_settings_name(tmp_path, make_isolated_pg_db):
    database = make_isolated_pg_db()
    settings = _settings(tmp_path, "postgres", database)
    _record_import(database, settings.data_dir)

    repository = build_plan_repository(settings)

    assert isinstance(repository, PostgresPlanRepository)
    assert repository.database.target_schema == settings.database_schema


def test_an_import_record_in_another_database_does_not_count(tmp_path, make_isolated_pg_db):
    # The record exists, but in a schema the settings do not name. Reading the
    # process-wide default instead of the given settings is exactly how this
    # passes when it should not.
    target_db = make_isolated_pg_db()
    other_db = make_isolated_pg_db()
    settings = _settings(tmp_path, "postgres", target_db)
    _record_import(other_db, settings.data_dir)

    with pytest.raises(ApplicationError) as raised:
        build_plan_repository(settings)

    assert raised.value.code == "CONFIGURATION_INVALID"


def test_the_activation_store_reads_the_versioned_profile(tmp_path, pg_db):
    # Confirmation has to read the constraints on its own transaction, so the
    # store it builds must carry that reader. Without it every candidate would be
    # refused for the wrong reason -- "no versioned store" instead of "this
    # constraint is not versioned yet".
    from backend.application.ports.profile_target_repository import (
        GoalVersionInput,
        ProfileVersionInput,
    )
    from backend.infrastructure.repositories.postgres_profile_target_repository import (
        PostgresProfileTargetRepository,
    )

    database = pg_db
    settings = _settings(tmp_path, "postgres", database)
    _record_import(database, settings.data_dir)
    profiles = PostgresProfileTargetRepository(database)
    setup = profiles.bootstrap(
        "alice",
        ProfileVersionInput(age=30, height_cm=175.0, weight_kg=70.0,
                            energy_parameter="male", activity_level="moderate",
                            auto_target_disabled=False, safety_conditions=(),
                            effective_from="2026-10-01"),
        GoalVersionInput(goal="fat_loss", effective_from="2026-10-01"),
    )

    repository = build_plan_activation_repository(settings, database=database)

    with database.connection() as connection:
        snapshot = repository.constraints_reader(connection, "alice")
    assert snapshot.versions["goal"] == setup.goal.id
    # No safety row has been written, so the allergy list is present-but-unversioned
    # rather than absent: the value exists, its version does not.
    assert snapshot.versions["allergies_or_restrictions"] is None
    assert "available_equipment" not in snapshot.versions
