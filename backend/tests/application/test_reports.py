import csv
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
import pandas as pd
from fastapi.testclient import TestClient

from backend.agent import graph as agent_graph
from backend.agent.graph import interpret_persisted_weekly_report
from backend.agent.planner import PlannerRoute
from backend.api import report as report_api
from backend.application.ports.report_repository import StoredWeeklyReport
from backend.application.use_cases.reports import WeeklyReports, iso_week_bounds
from backend.domain.errors import ApplicationError
from backend.config import get_settings
from backend.infrastructure.repositories.file_report_repository import FileReportRepository
from backend.infrastructure.user_lifecycle import user_lifecycle_guard
from backend.main import create_app
from backend.tools.data_access import DEFAULT_PROFILE, MEAL_COLUMNS, WORKOUT_COLUMNS


def _stored(week: str, title: str) -> StoredWeeklyReport:
    return StoredWeeklyReport(
        week=week,
        generated_at=datetime(2026, 8, 25, 9, 30, tzinfo=timezone.utc),
        report={"title": title, "sections": [], "checklist": [], "trace": {}},
    )


@pytest.fixture
def report_api_client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "user_profile.json").write_text(
        json.dumps(
            {
                "height_cm": 175,
                "weight_kg": 72,
                "age": 30,
                "gender": "male",
                "goal": "maintenance",
                "weekly_training_frequency": 3,
                "target_weight_kg": 72,
                "daily_calorie_target": 2200,
                "daily_protein_target": 130,
            }
        ),
        encoding="utf-8",
    )
    for name, columns in {
        "meals.csv": ["date", "meal", "food", "amount", "calories", "protein", "carbs", "fat"],
        "workouts.csv": ["date", "type", "exercise", "muscle_group", "sets", "reps", "weight", "duration_min"],
    }.items():
        with (data_dir / name).open("w", newline="", encoding="utf-8") as file:
            csv.writer(file).writerow(columns)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    try:
        yield TestClient(create_app()), data_dir
    finally:
        get_settings.cache_clear()


def test_file_repository_saves_lists_and_gets_reports_per_user(tmp_path):
    repository = FileReportRepository(tmp_path)

    repository.save("user-a", _stored("2026-W34", "Older"))
    repository.save("user-a", _stored("2026-W35", "Current"))

    assert [item.week for item in repository.list("user-a")] == ["2026-W35", "2026-W34"]
    assert repository.get("user-a", "2026-W35") == _stored("2026-W35", "Current")
    assert repository.get("user-a", "2026-W33") is None
    assert (tmp_path / "users" / "user-a" / "reports" / "2026-W35.json").is_file()


def test_file_repository_reads_are_blocked_after_user_deletion(tmp_path):
    repository = FileReportRepository(tmp_path)
    repository.save("deleted-user", _stored("2026-W35", "Private"))
    with user_lifecycle_guard(tmp_path, "deleted-user") as lifecycle:
        lifecycle.mark_deleted()

    for read in (lambda: repository.list("deleted-user"), lambda: repository.get("deleted-user", "2026-W35")):
        with pytest.raises(ApplicationError) as error:
            read()
        assert error.value.code == "AUTH_TOKEN_INVALID"


@pytest.mark.parametrize(
    "payload",
    [
        "{not-json",
        json.dumps(
            {
                "week": "2026-W35",
                "generated_at": "2026-08-25T09:30:00Z",
                "report": {"title": "Old shape", "sections": "not-a-list", "checklist": []},
            }
        ),
    ],
)
def test_corrupt_or_invalid_stored_reports_raise_a_controlled_error(tmp_path, payload):
    path = tmp_path / "users" / "user-a" / "reports" / "2026-W35.json"
    path.parent.mkdir(parents=True)
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ApplicationError) as error:
        FileReportRepository(tmp_path).get("user-a", "2026-W35")

    assert error.value.code == "REPORT_STORAGE_INVALID"
    assert error.value.processing_mode == "deterministic"


@pytest.mark.parametrize(
    "week",
    ["2026-W5", "2026-w05", "2026-W00", "2026-W54", "2021-W53", "../2026-W05"],
)
def test_iso_week_keys_are_strictly_validated(week):
    with pytest.raises(ApplicationError) as error:
        iso_week_bounds(week)

    assert error.value.code == "REPORT_WEEK_INVALID"


def test_iso_week_bounds_accept_real_week_53():
    assert tuple(day.isoformat() for day in iso_week_bounds("2020-W53")) == (
        "2020-12-28",
        "2021-01-03",
    )


def test_generation_is_explicit_and_persists_only_for_the_requesting_user(tmp_path):
    repository = FileReportRepository(tmp_path)
    calls = []

    def generate(user_id, start, end):
        calls.append((user_id, start.isoformat(), end.isoformat()))
        return {"title": "Generated", "sections": [], "checklist": [], "trace": {}}

    reports = WeeklyReports(
        repository,
        generate,
        now=lambda: datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc),
    )

    assert reports.list("user-a") == []
    assert calls == []

    saved = reports.generate("user-a", "2026-W35")

    assert calls == [("user-a", "2026-08-24", "2026-08-30")]
    assert saved.week == "2026-W35"
    assert reports.get("user-a", "2026-W35") == saved
    assert reports.list("user-b") == []
    assert repository.get("user-b", "2026-W35") is None


def test_agent_interprets_the_persisted_non_current_week_without_regenerating_it():
    archived = {
        "title": "Archived week 02",
        "sections": [{"title": "Archived fact", "content": "Only this report contains marker-02."}],
        "checklist": ["Keep marker-02"],
        "trace": {},
    }

    class Repository:
        def read_profile(self, user_id=None):
            return DEFAULT_PROFILE.model_copy()

        def read_meals(self, user_id=None):
            return pd.DataFrame(columns=MEAL_COLUMNS)

        def read_workouts(self, user_id=None):
            return pd.DataFrame(columns=WORKOUT_COLUMNS)

    class Gateway:
        model = "test-model"
        captured_state = None

        def plan_route(self, question):
            return PlannerRoute(intent="weekly_report", needs_report=True)

        def write_answer(self, state):
            self.captured_state = state
            return "Interpretation of marker-02"

    gateway = Gateway()
    result = interpret_persisted_weekly_report(
        week="2025-W02",
        report=archived,
        user_id="user-a",
        repository=Repository(),
        gateway=gateway,
    )

    assert gateway.captured_state["tool_results"]["weekly_report"] == archived
    assert gateway.captured_state["tool_results"]["report_week"] == "2025-W02"
    assert "2025-W02" in gateway.captured_state["user_query"]
    assert "load_persisted_weekly_report" in result["trace"]["tool_calls"]
    assert "generate_weekly_report" not in result["trace"]["tool_calls"]


def test_report_api_lists_gets_and_explicitly_generates_only_authenticated_users(report_api_client, monkeypatch):
    client, data_dir = report_api_client

    def register(username):
        response = client.post(
            "/auth/register",
            json={"username": username, "password": "password123", "display_name": username},
        )
        return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}

    user_a = register("report-user-a")
    user_b = register("report-user-b")

    assert client.get("/report/weekly").status_code == 401
    assert client.get("/report/weekly", headers=user_a).json()["data"] == []

    generated = client.post("/report/weekly/2026-W35/generate", headers=user_a)

    assert generated.status_code == 200
    assert generated.json()["processing_mode"] == "deterministic"
    assert generated.json()["data"]["week"] == "2026-W35"
    assert client.get("/report/weekly/2026-W35", headers=user_a).json()["data"] == generated.json()["data"]
    assert [item["week"] for item in client.get("/report/weekly", headers=user_a).json()["data"]] == ["2026-W35"]
    assert client.get("/report/weekly", headers=user_b).json()["data"] == []
    assert client.get("/report/weekly/2026-W35", headers=user_b).status_code == 404

    invalid = client.post("/report/weekly/2021-W53/generate", headers=user_a)
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "REPORT_WEEK_INVALID"

    archived = client.post("/report/weekly/2025-W02/generate", headers=user_a)
    assert archived.status_code == 200

    class CapturingGateway:
        model = "report-interpreter"
        captured_state = None

        def plan_route(self, question):
            return PlannerRoute(intent="weekly_report", needs_report=True)

        def write_answer(self, state):
            self.captured_state = state
            return "Archived report interpretation"

    gateway = CapturingGateway()
    monkeypatch.setattr(agent_graph, "resolve_user_model_gateway", lambda user_id: gateway)

    interpreted = client.post("/report/weekly/2025-W02/interpret", headers=user_a)

    assert interpreted.status_code == 200
    assert interpreted.json()["processing_mode"] == "agent"
    assert gateway.captured_state["tool_results"]["report_week"] == "2025-W02"
    assert gateway.captured_state["tool_results"]["weekly_report"] == archived.json()["data"]["report"]
    assert client.post("/report/weekly/2025-W02/interpret", headers=user_b).status_code == 404

    agent_started = threading.Event()
    release_agent = threading.Event()
    deletion_entered = threading.Event()
    user_id = client.get("/auth/me", headers=user_a).json()["data"]["user_id"]

    def slow_interpretation(**_kwargs):
        agent_started.set()
        assert release_agent.wait(timeout=2)
        return {
            "answer_markdown": "Guarded interpretation",
            "intent": "weekly_report",
            "trace": {},
            "sources": [],
            "model": "report-interpreter",
            "request_id": "guarded-request",
        }

    def delete_user():
        with user_lifecycle_guard(data_dir, user_id) as lifecycle:
            deletion_entered.set()
            lifecycle.mark_deleted()

    monkeypatch.setattr(report_api, "interpret_persisted_weekly_report", slow_interpretation)
    with ThreadPoolExecutor(max_workers=2) as executor:
        response_future = executor.submit(
            client.post,
            "/report/weekly/2025-W02/interpret",
            headers=user_a,
        )
        assert agent_started.wait(timeout=2)
        deletion_future = executor.submit(delete_user)
        deletion_was_blocked = not deletion_entered.wait(timeout=0.2)
        release_agent.set()
        guarded_response = response_future.result(timeout=2)
        deletion_future.result(timeout=2)

    assert deletion_was_blocked
    assert guarded_response.status_code == 200
