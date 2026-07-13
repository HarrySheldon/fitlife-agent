from fastapi.testclient import TestClient

from backend.application.use_cases.generate_plan import GeneratePlan
from backend.application.use_cases.generate_weekly_report import GenerateWeeklyReport
from backend.main import app
from backend.schemas import UserProfile
from backend.tools import data_access


client = TestClient(app)


class StubRepository:
    def read_profile(self, user_id=None):
        return data_access.DEFAULT_PROFILE.model_copy()

    def read_meals(self, user_id=None):
        return data_access.read_meals(None)

    def read_workouts(self, user_id=None):
        return data_access.read_workouts(None)

    def write_profile(self, profile: UserProfile, user_id=None):
        raise AssertionError("write_profile must not be called")

    def append_meal(self, record, user_id=None):
        raise AssertionError("append_meal must not be called")

    def append_workout(self, record, user_id=None):
        raise AssertionError("append_workout must not be called")


def test_weekly_report_use_case_is_structured_and_deterministic():
    result = GenerateWeeklyReport(StubRepository()).execute("user-a")

    assert result["title"] == "FitLife Weekly Report"
    assert result["trace"]["tool_calls"] == [
        "load_profile",
        "analyze_meals",
        "analyze_workouts",
        "generate_weekly_report",
    ]


def test_plan_use_case_is_structured_and_deterministic():
    result = GeneratePlan(StubRepository()).execute("user-a")

    assert result["diet_plan"]
    assert result["workout_plan"]
    assert result["trace"]["tool_calls"] == [
        "load_profile",
        "generate_next_week_plan",
        "validate_plan",
    ]


def test_report_and_plan_apis_mark_deterministic_processing():
    report_response = client.post("/report/weekly")
    plan_response = client.post("/plan/generate")

    assert report_response.status_code == 200
    assert report_response.json()["processing_mode"] == "deterministic"
    assert plan_response.status_code == 200
    assert plan_response.json()["processing_mode"] == "deterministic"
