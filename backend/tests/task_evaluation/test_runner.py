"""Runner isolation tests: two environments, one shared API contract."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app
from backend.task_evaluation.contracts import Scenario
from backend.task_evaluation.runner import NetworkAttempt, ScriptedGateway, execute_scenario
from backend.task_evaluation.observation import observe_database

_clients = []


@pytest.fixture(autouse=True)
def reset_settings_cache():
    yield
    while _clients:
        _clients.pop().__exit__(None, None, None)
    get_settings.cache_clear()


def test_spawn_worker_isolated_and_deadline():
    import time
    from backend.task_evaluation.runner import run_isolated_scenario
    scenario = Scenario.model_validate({"id": "spawn-empty", "version": 1, "expected": {"confirmed_meals": 0}})
    result = run_isolated_scenario(scenario, deadline=time.monotonic() + 30)
    assert result.status == "passed", result
    sleeping = scenario.model_copy(update={"initial_state": scenario.initial_state.model_copy(update={"faults": scenario.initial_state.faults.model_copy(update={"sleep_seconds": 2})})})
    result = run_isolated_scenario(sleeping, deadline=time.monotonic() + 0.1)
    assert result.status == "deadline_exceeded"


def test_structured_refs_preserve_types_and_reject_unknown():
    from backend.task_evaluation.runner import _resolve, CaseError
    assert _resolve({"value": {"$ref": "version"}, "other": [True, 3]}, {"version": 2}) == {"value": 2, "other": [True, 3]}
    with pytest.raises(CaseError):
        _resolve({"$ref": "unknown"}, {})


def _build_client(tmp_path: Path, monkeypatch) -> TestClient:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(data_dir / "fitlife.sqlite3"))
    get_settings.cache_clear()
    # Enter the context so the lifespan hook runs migrations and catalog seeding.
    client = TestClient(create_app())
    client.__enter__()
    _clients.append(client)
    return client


def _register(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/auth/register",
        json={"username": username, "password": "password123", "display_name": username},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _seed_profile(client: TestClient, headers: dict[str, str]) -> None:
    response = client.put(
        "/api/v1/profile",
        headers=headers,
        json={
            "age": 30,
            "height_cm": 175,
            "weight_kg": 70,
            "energy_parameter": "neutral",
            "activity_level": "moderate",
            "auto_target_disabled": False,
            "safety_conditions": [],
            "effective_from": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 200


def test_two_isolated_environments_do_not_share_records(tmp_path, monkeypatch):
    """The core isolation property: environment B starts empty no matter what A did."""
    scenario = Scenario.model_validate({
        "id": "entry-confirm", "version": 1,
        "steps": [
            {
                "method": "POST",
                "path": "/api/v1/smart-entry-drafts",
                "body": {"log_date": "2026-07-26", "raw_text": "早餐：白飯 100g"},
                "capture": {"draft_id": "data.id", "version": "data.version"},
            },
            {
                "method": "POST",
                "path": "/api/v1/smart-entry-drafts/{draft_id}/confirm",
                "headers": {"If-Match": "{version}", "Idempotency-Key": "00000000-0000-0000-0000-000000000001"},
                "expected_status": 200,
                "capture": {"meal_ids": "data.meal_ids"},
            },
        ],
        "expected": {"confirmed_meals": 1},
    })

    env_a = tmp_path / "a"
    env_a.mkdir()
    client_a = _build_client(env_a, monkeypatch)
    headers_a = _register(client_a, "user-a")
    _seed_profile(client_a, headers_a)
    result_a = execute_scenario(
        scenario, client_a, headers_factory=lambda: headers_a,
        observer=lambda: observe_database(env_a / "data" / "fitlife.sqlite3")
    )
    assert result_a.status == "passed", result_a.failures

    env_b = tmp_path / "b"
    env_b.mkdir()
    client_b = _build_client(env_b, monkeypatch)
    headers_b = _register(client_b, "user-b")
    _seed_profile(client_b, headers_b)
    today = client_b.get("/today", params={"date": "2026-07-26"}, headers=headers_b)
    assert today.status_code == 200
    assert today.json()["data"]["consumed"]["calories"] == 0
    assert today.json()["data"]["recorded_meal_count"] == 0


def test_scripted_gateway_refuses_any_network_call():
    gateway = ScriptedGateway()

    with pytest.raises(NetworkAttempt):
        gateway.write_answer({})
    with pytest.raises(NetworkAttempt):
        gateway.parse_structured(instructions="x", input_text="y", response_model=dict)


def test_a_missing_variable_reference_is_a_case_error(tmp_path, monkeypatch):
    scenario = Scenario.model_validate({
        "id": "broken", "version": 1,
        "steps": [
            {
                "method": "POST",
                "path": "/api/v1/smart-entry-drafts/{draft_id}/confirm",
                "expected_status": 200,
            }
        ],
        "expected": {},
    })
    client = _build_client(tmp_path / "c", monkeypatch)
    headers = _register(client, "user-c")

    with pytest.raises(Exception) as raised:
        execute_scenario(scenario, client, headers_factory=lambda: headers)

    assert "draft_id" in str(raised.value)


def test_scenario_path_rejects_urls():
    with pytest.raises(Exception):
        Scenario.model_validate({
            "id": "x", "version": 1,
            "steps": [{"method": "GET", "path": "https://example.com"}],
            "expected": {},
        })


def test_same_scenario_twice_with_same_idempotency_key_replays_not_duplicates(tmp_path, monkeypatch):
    """Idempotency: replaying the same confirmation must not create new records."""
    env = tmp_path / "idem"
    env.mkdir()
    client = _build_client(env, monkeypatch)
    headers = _register(client, "idem-user")
    _seed_profile(client, headers)

    created = client.post(
        "/api/v1/smart-entry-drafts",
        headers=headers,
        json={"log_date": "2026-07-26", "raw_text": "早餐：白飯 100g"},
    )
    draft = created.json()["data"]

    scenario = Scenario.model_validate({
        "id": "entry-idempotent", "version": 1,
        "steps": [
            {
                "method": "POST",
                "path": f"/api/v1/smart-entry-drafts/{draft['id']}/confirm",
                "headers": {
                    "If-Match": str(draft["version"]),
                    "Idempotency-Key": "11111111-1111-1111-1111-111111111111",
                },
                "expected_status": 200,
                "capture": {"meal_ids": "data.meal_ids"},
            },
        ],
        "expected": {},
    })

    first = execute_scenario(scenario, client, headers_factory=lambda: headers)
    second = execute_scenario(scenario, client, headers_factory=lambda: headers)
    assert first.status == second.status == "passed"

    today = client.get("/today", params={"date": "2026-07-26"}, headers=headers)
    # Replayed confirmation produced one recorded meal, not two.
    assert today.json()["data"]["recorded_meal_count"] == 1


def test_runner_rejects_an_existing_storage_path_as_a_temp_dir(tmp_path, monkeypatch):
    """The runner must never point an evaluation at a real data directory."""
    from backend.task_evaluation.runner import reject_nonempty_workspace

    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "user_profile.json").write_text("{}", encoding="utf-8")

    with pytest.raises(Exception):
        reject_nonempty_workspace(real_dir)


def test_a_crashed_worker_is_reported_not_swallowed():
    """A worker that dies without answering must surface as an infrastructure error."""
    import time
    from backend.task_evaluation.runner import run_isolated_scenario

    scenario = Scenario.model_validate({
        "id": "crash", "version": 1,
        "initial_state": {"faults": {"crash_worker": True}},
        "expected": {},
    })
    result = run_isolated_scenario(scenario, deadline=time.monotonic() + 30)
    assert result.status == "worker_error"


def test_spawned_duplicate_scenarios_and_production_env_trap(tmp_path, monkeypatch):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from backend.task_evaluation.runner import run_isolated_scenario
    from backend.task_evaluation.budget import BatchBudget
    production = tmp_path / "production-trap"
    production.mkdir()
    marker = production / "sentinel.txt"
    marker.write_text("unchanged", encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(production))
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(production / "must-not-exist.sqlite3"))
    scenario = Scenario.model_validate({"id": "duplicate", "version": 1, "expected": {"confirmed_meals": 0}})
    budget = BatchBudget(200, 200000)
    deadline = time.monotonic() + 30
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: run_isolated_scenario(scenario, deadline=deadline, budget=budget), range(2)))
    assert all(result.status == "passed" for result in results), results
    assert marker.read_text(encoding="utf-8") == "unchanged"
    assert list(production.iterdir()) == [marker]


def test_crashed_worker_cleans_its_owned_workspace(monkeypatch):
    import tempfile
    import time
    import backend.task_evaluation.runner as runner
    real_factory = tempfile.TemporaryDirectory
    roots = []
    def tracked_factory(*args, **kwargs):
        workspace = real_factory(*args, **kwargs)
        roots.append(Path(workspace.name))
        return workspace
    monkeypatch.setattr(runner.tempfile, "TemporaryDirectory", tracked_factory)
    scenario = Scenario.model_validate({"id": "crash-clean", "version": 1, "initial_state": {"faults": {"crash_worker": True}}})
    result = runner.run_isolated_scenario(scenario, deadline=time.monotonic() + 30)
    assert result.status == "worker_error"
    assert result.metrics["cleanup_status"] == "completed"
    assert roots and all(not root.exists() for root in roots)


def test_real_baseline_suite_passes_after_spawn_serialization():
    import json
    import time
    from backend.task_evaluation.contracts import Suite
    from backend.task_evaluation.budget import BatchBudget
    from backend.task_evaluation.runner import run_suite
    suite_path = Path(__file__).resolve().parents[2] / "task_evaluation" / "scenarios" / "baseline.json"
    suite = Suite.model_validate(json.loads(suite_path.read_text(encoding="utf-8")))
    records = run_suite(suite.scenarios, mode="mock", deadline=time.monotonic() + 90, budget=BatchBudget(200))
    assert len(records) == 6
    assert all(record.success for record in records), [(record.case_id, record.error_class) for record in records]
