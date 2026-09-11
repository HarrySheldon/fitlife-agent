"""Versioned planner recovery boundary; contains no user or model prose."""
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.agent.planner import PlannerRoute


class CheckpointRoute(PlannerRoute):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent: Literal["weekly_report", "plan_generation", "mixed", "meal_analysis", "workout_analysis", "knowledge_qa"]


class PlannerCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    next_step: Literal["profile_loader"]
    route: CheckpointRoute


def restore_planner_state(checkpoint: dict) -> dict:
    """Rebuild only planner output after validation.

    Combine with the original AgentCommand, then reload profile, analyses and
    retrieval. This skips only planner, never input guards or output review;
    it neither restores arbitrary state nor automatically replays a run.
    """
    saved = PlannerCheckpoint.model_validate(checkpoint)
    if type(checkpoint["schema_version"]) is not int:
        raise ValueError("Invalid checkpoint schema version")
    return {"intent": saved.route.intent, "tool_requests": saved.route.model_dump(), "llm_used": True}
