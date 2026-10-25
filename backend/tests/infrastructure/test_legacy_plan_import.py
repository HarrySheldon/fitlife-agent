"""The import copies a directory and records that it did.

What these tests protect is the difference between "the files are still there"
and "the files are the authority". The import never deletes, so a mistake here is
recoverable; a *partial* import that flipped the switch would not be, because the
missing plans would simply not appear and nothing would look broken.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.application.ports.plan_repository import StoredPlan
from backend.domain.errors import ApplicationError
from backend.infrastructure.repositories.sqlite_plan_repository import (
    SQLitePlanRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.import_legacy_plans import (
    apply,
    inventory,
    main,
)
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)

DOCUMENT = {
    "diet_plan": {"meals": ["燕麦粥"], "daily_calorie_target": 1800,
                  "daily_protein_target": 120},
    "workout_plan": {"days": [{"day": "周一", "exercises": [{"name": "深蹲"}]}],
                     "weekly_training_days": 3, "rest_days": ["周日"]},
    "validation": {"passed": True, "warnings": [], "violations": [],
                   "repair_suggestions": []},
}


def _plan_file(directory, plan_id, *, when=NOW, document=None, based_on=None,
               kind="deterministic"):
    directory.mkdir(parents=True, exist_ok=True)
    plan = StoredPlan(plan_id=plan_id, activated_at=when, kind=kind,
                      based_on_plan_id=based_on, plan=document or DOCUMENT)
    (directory / f"{plan_id}.json").write_text(
        json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8")
    return plan


def _draft_file(directory, draft_id, *, when=NOW):
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "draft_id": draft_id, "created_at": when.isoformat(), "kind": "deterministic",
        "based_on_plan_id": None, "plan": DOCUMENT,
    }
    (directory / f"{draft_id}.json").write_text(json.dumps(payload, ensure_ascii=False),
                                                encoding="utf-8")


def _data_dir(tmp_path):
    return tmp_path / "data"


def _database(tmp_path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    return database


def _seeded(tmp_path):
    data_dir = _data_dir(tmp_path)
    owner = data_dir / "users" / "alice"
    _plan_file(owner / "plans", "plan-aaaaaaaa", when=NOW - timedelta(days=1))
    _plan_file(owner / "plans", "plan-bbbbbbbb", when=NOW, based_on="plan-aaaaaaaa",
               kind="agent_adjusted")
    _draft_file(owner / "plan-drafts", "draft-" + "c" * 32)
    return data_dir


# ----------------------------------------------------------------- the inventory


def test_the_inventory_counts_plans_and_drafts_without_writing(tmp_path):
    data_dir = _seeded(tmp_path)

    found = inventory(data_dir)

    assert found.owners.keys() == {"alice"}
    assert found.plan_count == 2
    assert found.draft_count == 1
    assert found.refused == []
    assert not (data_dir / "fitlife.sqlite3").exists()


def test_the_head_is_computed_by_the_legacy_rule(tmp_path):
    found = inventory(_seeded(tmp_path))

    head = found.owners["alice"].head

    assert head.plan_id == "plan-bbbbbbbb"
    assert head.revision == 2


def test_a_plan_outside_the_owner_directory_is_refused(tmp_path):
    data_dir = _data_dir(tmp_path)
    stray = data_dir / "users" / "alice" / "plan-aaaaaaaa.json"
    stray.parent.mkdir(parents=True)
    stray.write_text(json.dumps({"plan_id": "plan-aaaaaaaa"}), encoding="utf-8")

    found = inventory(data_dir)

    assert [path for path, _reason in found.refused] == [str(stray)]


def test_an_owner_directory_that_is_not_a_user_id_is_refused(tmp_path):
    data_dir = _data_dir(tmp_path)
    _plan_file(data_dir / "users" / "not a user id" / "plans", "plan-aaaaaaaa")

    found = inventory(data_dir)

    assert found.owners == {}
    assert len(found.refused) == 1


def test_a_quarantined_account_is_not_data(tmp_path):
    data_dir = _data_dir(tmp_path)
    _plan_file(data_dir / "users" / ".delete-alice-abc.quarantine" / "plans",
               "plan-aaaaaaaa")

    found = inventory(data_dir)

    assert found.owners == {} and found.refused == []


def test_an_unreadable_plan_file_is_refused_rather_than_skipped(tmp_path):
    data_dir = _data_dir(tmp_path)
    plans = data_dir / "users" / "alice" / "plans"
    plans.mkdir(parents=True)
    (plans / "plan-aaaaaaaa.json").write_text("{not json", encoding="utf-8")

    found = inventory(data_dir)

    assert found.owners["alice"].plans == []
    assert len(found.refused) == 1


def test_a_stray_note_is_ignored_rather_than_refused(tmp_path):
    data_dir = _seeded(tmp_path)
    (data_dir / "users" / "alice" / "plans" / "README.md").write_text("hi", encoding="utf-8")

    found = inventory(data_dir)

    assert found.refused == []
    assert found.plan_count == 2


# --------------------------------------------------------------------- the apply


def test_apply_copies_history_and_records_the_import(tmp_path):
    data_dir = _seeded(tmp_path)
    database = _database(tmp_path)

    imported = apply(data_dir, database)

    assert imported == {"owners": 1, "plans": 2, "drafts": 1}
    repository = SQLitePlanRepository(database)
    assert [plan.plan_id for plan in repository.list("alice")] == [
        "plan-bbbbbbbb", "plan-aaaaaaaa"]
    assert repository.get("alice", "plan-aaaaaaaa").plan.diet_plan == DOCUMENT["diet_plan"]
    head = repository.current_head("alice")
    assert head.plan_id == "plan-bbbbbbbb" and head.revision == 2
    with database.connection() as connection:
        state = connection.execute("SELECT * FROM plan_import_state").fetchone()
    assert state["plan_count"] == 2 and state["owner_count"] == 1


def test_apply_keeps_the_files(tmp_path):
    data_dir = _seeded(tmp_path)
    before = sorted(path.name for path in (data_dir / "users" / "alice" / "plans").iterdir())

    apply(data_dir, _database(tmp_path))

    assert sorted(path.name for path in
                  (data_dir / "users" / "alice" / "plans").iterdir()) == before


def test_applying_twice_does_not_duplicate_history(tmp_path):
    data_dir = _seeded(tmp_path)
    database = _database(tmp_path)

    first = apply(data_dir, database)
    second = apply(data_dir, database)

    assert first["plans"] == 2
    # The second run copies nothing new: identical rows are no-ops.
    assert second == {"owners": 1, "plans": 0, "drafts": 0}
    assert len(SQLitePlanRepository(database).list("alice")) == 2
    assert SQLitePlanRepository(database).current_head("alice").revision == 2


def test_a_different_document_under_the_same_id_is_a_conflict(tmp_path):
    data_dir = _seeded(tmp_path)
    database = _database(tmp_path)
    repository = SQLitePlanRepository(database)
    repository.save("alice", StoredPlan(
        plan_id="plan-aaaaaaaa", activated_at=NOW, kind="deterministic",
        plan={**DOCUMENT, "trace": {"different": True}}))

    with pytest.raises(ApplicationError) as raised:
        apply(data_dir, database)

    assert raised.value.code == "PLAN_HISTORY_CONFLICT"


def test_a_refused_file_aborts_the_import_before_anything_is_written(tmp_path):
    data_dir = _seeded(tmp_path)
    (data_dir / "users" / "alice" / "plans" / "plan-zzz.json").write_text(
        "{}", encoding="utf-8")
    database = _database(tmp_path)

    with pytest.raises(SystemExit):
        apply(data_dir, database)

    assert SQLitePlanRepository(database).list("alice") == []


def test_the_head_never_moves_backwards(tmp_path):
    data_dir = _seeded(tmp_path)
    database = _database(tmp_path)
    apply(data_dir, database)
    repository = SQLitePlanRepository(database)
    repository.save("alice", StoredPlan(
        plan_id="plan-dddddddd", activated_at=NOW + timedelta(days=1),
        kind="agent_adjusted", based_on_plan_id="plan-bbbbbbbb", plan=DOCUMENT))
    assert repository.current_head("alice").revision == 3

    # The directory still holds two plans; the database knows three. Re-importing
    # adds nothing and leaves the newer head alone.
    apply(data_dir, database)

    assert repository.current_head("alice").revision == 3


# ------------------------------------------------------------------ the command


def test_dry_run_prints_a_report_and_writes_nothing(tmp_path, capsys):
    data_dir = _seeded(tmp_path)

    exit_code = main(["--data-dir", str(data_dir), "--dry-run"])

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["plans"] == 2 and report["owners"] == 1
    assert not (data_dir / "fitlife.sqlite3").exists()


def test_dry_run_exits_non_zero_when_a_file_is_refused(tmp_path, capsys):
    data_dir = _data_dir(tmp_path)
    stray = data_dir / "users" / "alice" / "plan-aaaaaaaa.json"
    stray.parent.mkdir(parents=True)
    stray.write_text("{}", encoding="utf-8")

    assert main(["--data-dir", str(data_dir), "--dry-run"]) == 1
    assert json.loads(capsys.readouterr().out)["refused"]


def test_apply_runs_the_migrations_it_needs(tmp_path, capsys):
    data_dir = _seeded(tmp_path)

    exit_code = main(["--data-dir", str(data_dir), "--apply"])

    assert exit_code == 0
    database = SQLiteDatabase(data_dir / "fitlife.sqlite3")
    assert len(SQLitePlanRepository(database).list("alice")) == 2
