"""End-to-end HTTP integration test across M1–M4 API routes."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.infrastructure.sqlite import runtime as sqlite_runtime
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS
from backend.main import create_app


def test_m1_to_m4_http_end_to_end_flow(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "fitlife.sqlite3"
    db = SQLiteDatabase(db_path)
    run_migrations(db, RECORDS_MIGRATIONS)

    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("LLM_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(sqlite_runtime, "get_database", lambda: db)

    app = create_app()
    client = TestClient(app)

    # Register & authenticate a fresh user
    reg = client.post(
        "/auth/register",
        json={
            "username": "m4_e2e_user",
            "password": "Password123!",
            "display_name": "E2E Tester",
        },
    )
    assert reg.status_code in (200, 201), reg.text
    token = reg.json()["data"]["access_token"]
    user_id = reg.json()["data"]["user"]["user_id"]
    headers = {"Authorization": f"Bearer {token}"}

    # Insert minimal profile version required for workout draft creation
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO user_profile_versions (
                id, user_id, age, height_cm, weight_kg, energy_parameter,
                activity_level, effective_from
            )
            VALUES ('pv-1', ?, 30, 175, 72.0, 'male', 'moderate', '2026-01-01T00:00:00Z')
            """,
            (user_id,),
        )

    # M1: Log body measurements & save structured training context
    bm = client.post(
        "/api/v1/body-measurements",
        headers=headers,
        json={"weight_kg": 71.5, "body_fat_pct": 18.0, "waist_cm": 82.0, "note": "morning"},
    )
    assert bm.status_code == 201, bm.text
    assert bm.json()["data"]["summary"]["latest_weight_kg"] == 71.5

    tc = client.put(
        "/api/v1/training-context",
        headers=headers,
        json={
            "available_equipment": ["barbell", "dumbbell", "bodyweight"],
            "weekly_available_days": 4,
            "session_duration_min": 50,
            "experience_level": "intermediate",
            "preferred_split": "upper_lower",
            "injury_or_limitations": [{"area": "knee", "note": "no jumping"}],
            "notes": "morning preferred",
        },
    )
    assert tc.status_code == 200, tc.text
    assert tc.json()["data"]["training_context"]["configured"] is True

    # M2: Fetch Progress overview
    prog = client.get("/api/v1/progress/overview?days=30", headers=headers)
    assert prog.status_code == 200, prog.text
    assert prog.json()["data"]["kpis"]["latest_weight_kg"] == 71.5

    # M3: Create cycle draft -> explicitly activate -> query active & today -> prefill workout draft
    draft_res = client.post(
        "/api/v1/plan-cycles",
        headers=headers,
        json={"title": "E2E 4-Week Block", "goal_type": "fat_loss", "duration_weeks": 4},
    )
    assert draft_res.status_code == 201, draft_res.text
    cycle_id = draft_res.json()["data"]["cycle"]["id"]
    assert draft_res.json()["data"]["cycle"]["status"] == "draft"

    act = client.post(f"/api/v1/plan-cycles/{cycle_id}/activate", headers=headers)
    assert act.status_code == 200, act.text
    assert act.json()["data"]["cycle"]["status"] == "active"

    active_view = client.get("/api/v1/plan-cycles/active", headers=headers)
    assert active_view.status_code == 200, active_view.text
    training_day = next(
        d for d in active_view.json()["data"]["days"] if d["day_type"] != "rest"
    )

    prefill = client.post(f"/api/v1/plan-cycles/days/{training_day['id']}/prefill-workout", headers=headers)
    assert prefill.status_code == 201, prefill.text
    assert prefill.json()["data"]["draft_id"]

    # M4: Weekly lazy automation check (idempotent) + on-demand personalized draft
    auto1 = client.post("/api/v1/weekly-automation/check", headers=headers)
    assert auto1.status_code == 200, auto1.text
    auto2 = client.post("/api/v1/weekly-automation/check", headers=headers)
    assert auto2.status_code == 200
    assert auto2.json()["data"]["run"]["iso_week"] == auto1.json()["data"]["run"]["iso_week"]
    assert auto2.json()["data"]["run"]["draft_cycle_id"] == auto1.json()["data"]["run"]["draft_cycle_id"]

    pers = client.post(
        "/api/v1/plan-cycles/generate-personalized",
        headers=headers,
        json={"duration_weeks": 4, "focus_note": "prioritize back strength"},
    )
    assert pers.status_code == 201, pers.text
    assert pers.json()["data"]["cycle"]["status"] == "draft"

    get_settings.cache_clear()


def test_progress_overview_uses_sqlite_setup_instead_of_default_profile(tmp_path: Path, monkeypatch):
    from backend.application.ports.profile_target_repository import (
        GoalVersionInput,
        ProfileVersionInput,
        TargetVersionInput,
    )
    from backend.infrastructure.repositories.sqlite_profile_target_repository import (
        SQLiteProfileTargetRepository,
    )

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "fitlife.sqlite3"
    db = SQLiteDatabase(db_path)
    run_migrations(db, RECORDS_MIGRATIONS)

    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("LLM_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(sqlite_runtime, "get_database", lambda: db)

    app = create_app()
    client = TestClient(app)

    reg = client.post(
        "/auth/register",
        json={
            "username": "sqlite_truth_user",
            "password": "Password123!",
            "display_name": "SQLite Truth User",
        },
    )
    assert reg.status_code in (200, 201), reg.text
    token = reg.json()["data"]["access_token"]
    user_id = reg.json()["data"]["user"]["user_id"]
    headers = {"Authorization": f"Bearer {token}"}

    repo = SQLiteProfileTargetRepository(db)
    profile_v = repo.append_profile(
        user_id,
        ProfileVersionInput(
            age=26,
            height_cm=175.0,
            weight_kg=70.0,
            energy_parameter="male",
            activity_level="moderate",
            auto_target_disabled=False,
            safety_conditions=(),
            effective_from="2026-11-01T00:00:00Z",
        ),
    )
    goal_v = repo.append_goal(
        user_id,
        GoalVersionInput(goal="maintenance", effective_from="2026-11-01T00:00:00Z"),
    )
    repo.append_target(
        user_id,
        TargetVersionInput(
            profile_version_id=profile_v.id,
            overall_goal_version_id=goal_v.id,
            calories=2090.0,
            carbs=261.0,
            protein=112.0,
            fat=66.0,
            source="deterministic_calculation",
            formula_version="v1",
            rationale={},
            effective_from="2026-11-01T00:00:00Z",
        ),
    )

    prog = client.get("/api/v1/progress/overview?days=30", headers=headers)
    assert prog.status_code == 200, prog.text
    kpis = prog.json()["data"]["kpis"]
    assert kpis["target_weight_kg"] is None
    assert kpis["adherence_planned"] == 3
    assert kpis["daily_calorie_target"] == 2090.0
    assert kpis["daily_protein_target"] == 112.0

    # Simulate partial LegacyProfileProjection from onboarding/profile edits
    # (updates weight/goal/calorie/protein while leaving synthetic target_weight_kg=68 and weekly_training_frequency=4)
    from backend.tools.data_access import update_profile_atomically
    update_profile_atomically(
        lambda current: current.model_copy(
            update={
                "weight_kg": 70.0,
                "goal": "maintenance",
                "daily_calorie_target": 2090,
                "daily_protein_target": 112,
            }
        ),
        user_id,
    )
    prog_projected = client.get("/api/v1/progress/overview?days=30", headers=headers)
    assert prog_projected.status_code == 200, prog_projected.text
    kpis_projected = prog_projected.json()["data"]["kpis"]
    assert kpis_projected["target_weight_kg"] is None
    assert kpis_projected["adherence_planned"] == 3

    bm_list = client.get("/api/v1/body-measurements?days=30", headers=headers)
    assert bm_list.status_code == 200, bm_list.text
    assert bm_list.json()["data"]["summary"]["target_weight_kg"] is None

    draft_res = client.post(
        "/api/v1/plan-cycles",
        headers=headers,
        json={"duration_weeks": 4},
    )
    assert draft_res.status_code == 201, draft_res.text
    assert draft_res.json()["data"]["cycle"]["goal_type"] == "maintenance"

    get_settings.cache_clear()
