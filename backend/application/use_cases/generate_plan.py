from __future__ import annotations

from backend.application.ports.fitness_repository import FitnessRepository
from backend.tools.report_generator import generate_next_week_plan


class GeneratePlan:
    def __init__(self, repository: FitnessRepository) -> None:
        self.repository = repository

    def execute(self, user_id: str | None = None) -> dict:
        profile = self.repository.read_profile(user_id)
        plan = generate_next_week_plan(profile.model_dump())
        plan["trace"] = {
            "tool_calls": ["load_profile", "generate_next_week_plan", "validate_plan"]
        }
        return plan
