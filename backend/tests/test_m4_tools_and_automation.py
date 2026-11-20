"""M4 backend tests: catalog/progress Agent tools, colloquial food BM25 fallback, and weekly automation."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from backend.agent.persistence import safe_payload
from backend.agent.tools.contracts import (
    CatalogExerciseSearchArgs,
    CatalogFoodSearchArgs,
    ProgressQueryArgs,
)
from backend.agent.tools.handlers import (
    BoundFitnessReads,
    search_public_exercises,
    search_public_foods,
)
from backend.agent.tools.registry import RECORDED_TOOL_NAMES, SPECS
from backend.application.use_cases.weekly_automation import WeeklyAutomationService
from backend.infrastructure.repositories.sqlite_body_measurement_repository import (
    SQLiteBodyMeasurementRepository,
)
from backend.infrastructure.repositories.sqlite_food_catalog_repository import (
    SQLiteFoodCatalogRepository,
)
from backend.infrastructure.repositories.sqlite_plan_cycle_repository import (
    SQLitePlanCycleRepository,
)
from backend.infrastructure.sqlite import runtime as sqlite_runtime
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


def _db(tmp_path: Path, monkeypatch) -> SQLiteDatabase:
    db = SQLiteDatabase(tmp_path / "m4.sqlite3")
    run_migrations(db, RECORDS_MIGRATIONS)
    monkeypatch.setattr(sqlite_runtime, "get_database", lambda: db)
    return db


def test_new_agent_tools_are_registered_read_only_and_event_allowlisted():
    for name in ("catalog.search_foods", "catalog.search_exercises", "fitness.progress"):
        assert name in SPECS
        assert name in RECORDED_TOOL_NAMES
        assert SPECS[name].read_only is True
        validated = safe_payload({"agent_tool": name})
        assert validated["agent_tool"] == name

    assert SPECS["catalog.search_foods"].effect == "public_read"
    assert SPECS["catalog.search_exercises"].effect == "public_read"
    assert SPECS["fitness.progress"].effect == "private_read"
    assert SPECS["fitness.progress"].required_domains(ProgressQueryArgs(aspect="exercise_progress")) == frozenset({"training"})
    assert SPECS["fitness.progress"].required_domains(ProgressQueryArgs(aspect="training_context")) == frozenset({"profile", "training"})


def test_colloquial_chinese_food_search_bm25_fallback_and_public_isolation(tmp_path: Path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO food_catalog (
                id, owner_user_id, source, source_name, source_record_id,
                name, basis_type, basis_amount, unit, calories, carbs, protein, fat, active
            )
            VALUES
                ('f-pub-1', NULL, 'public', 'test', 'pub-1', '鸡胸肉', 'per_100g', 100, 'g', 133, 0, 24.6, 2.5, 1),
                ('f-priv-1', 'u-secret', 'user_custom', 'user', 'priv-1', '私密鸡胸肉', 'per_100g', 100, 'g', 150, 0, 25, 3, 1)
            """
        )
        conn.execute(
            """
            INSERT INTO catalog_search (catalog_kind, catalog_id, name, aliases, pinyin, source_tokens)
            VALUES
                ('food', 'f-pub-1', '鸡胸肉', '', '', '鸡胸肉 鸡胸 胸肉'),
                ('food', 'f-priv-1', '私密鸡胸肉', '', '', '私密鸡胸肉 私密 密鸡 鸡胸 胸肉')
            """
        )

    # Colloquial query "水煮鸡胸肉" fails strict AND ("水煮" missing) -> BM25 OR fallback finds "鸡胸肉"
    repo = SQLiteFoodCatalogRepository(db)
    hits = repo.search("u1", "水煮鸡胸肉", limit=5)
    assert len(hits) == 1
    assert hits[0].id == "f-pub-1"

    # Public Agent tool must never return private custom foods
    public_hits = search_public_foods("鸡胸肉", limit=5)
    assert [item["id"] for item in public_hits] == ["f-pub-1"]


def test_public_exercise_search_filters_by_equipment_and_muscle(tmp_path: Path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO exercise_catalog (
                id, owner_user_id, source, source_name, source_record_id,
                name, exercise_type, primary_muscle, provenance_json, active
            )
            VALUES
                ('e1', NULL, 'public', 'test', '1', '哑铃卧推', 'strength', '胸肌', '{"equipment":"dumbbell","mechanic":"compound","level":"beginner"}', 1),
                ('e2', NULL, 'public', 'test', '2', '杠铃卧推', 'strength', '胸肌', '{"equipment":"barbell","mechanic":"compound","level":"intermediate"}', 1),
                ('e3', NULL, 'public', 'test', '3', '杠铃深蹲', 'strength', '股四头肌', '{"equipment":"barbell","mechanic":"compound","level":"intermediate"}', 1)
            """
        )

    dumbbell_chest = search_public_exercises(muscle_group="胸肌", equipment="dumbbell", limit=5)
    assert [item["id"] for item in dumbbell_chest] == ["e1"]

    barbell_all = search_public_exercises(equipment="barbell", limit=5)
    assert {item["id"] for item in barbell_all} == {"e2", "e3"}


def test_fitness_progress_tool_enforces_domain_scope_and_reads_owner_data(tmp_path: Path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    SQLiteBodyMeasurementRepository(db).create("u1", measured_date="2026-11-18", weight_kg=71.2)
    SQLiteBodyMeasurementRepository(db).create("u2", measured_date="2026-11-18", weight_kg=55.0)

    class _DummyRepo:
        def read_profile(self, _uid):
            raise RuntimeError("unused")

    reads = BoundFitnessReads(_DummyRepo(), "u1")
    body = reads.query_progress(ProgressQueryArgs(aspect="body_trend", days=30), frozenset({"profile"}))
    assert body["latest_weight_kg"] == 71.2

    # Without 'training' domain, exercise_progress must raise SCOPE_PERMISSION_REQUIRED
    try:
        reads.query_progress(ProgressQueryArgs(aspect="exercise_progress", days=30), frozenset({"profile"}))
        raise AssertionError("Expected PermissionError")
    except PermissionError as err:
        assert str(err) == "SCOPE_PERMISSION_REQUIRED"


def test_weekly_automation_is_idempotent_and_never_auto_activates_draft(tmp_path: Path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    service = WeeklyAutomationService(db)
    report_calls: list[tuple[str, str]] = []

    def _fake_ensure_report(uid: str, week: str) -> str:
        report_calls.append((uid, week))
        return "generated"

    run1 = service.check_and_run(
        "u1",
        date(2026, 11, 20),
        goal_type="fat_loss",
        ensure_weekly_report=_fake_ensure_report,
    )
    assert run1.iso_week == "2026-W47"
    assert run1.report_week == "2026-W46"
    assert run1.report_status == "generated"
    assert run1.draft_status == "generated_deterministic"
    assert run1.draft_cycle_id is not None

    # Draft must NOT be auto-activated
    cycle_repo = SQLitePlanCycleRepository(db)
    assert cycle_repo.get_active_cycle("u1") is None
    draft = cycle_repo.get_cycle("u1", run1.draft_cycle_id)
    assert draft is not None and draft.status == "draft"

    # Second call in same week is strictly idempotent
    run2 = service.check_and_run(
        "u1",
        date(2026, 11, 20),
        goal_type="fat_loss",
        ensure_weekly_report=_fake_ensure_report,
    )
    assert run2 == run1
    assert len(report_calls) == 1

    assert service.dismiss("u1", "2026-W47") is True
    assert service.get_run("u1", "2026-W47").dismissed is True
