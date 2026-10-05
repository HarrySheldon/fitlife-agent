"""Versioned planner recovery boundary; contains no user or model prose."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from backend.agent.route_contract import PlannerRoute

# A live provider classifies in its own words ("nutrition_analysis",
# "meal_summary", "fat_loss_training_plan"). That label is carried for the trace
# and the deterministic writer, while the routing flags drive the workflow. So
# this boundary bounds the *shape* of a label instead of enumerating a taxonomy:
# an off-taxonomy label must never be able to abort a run.
IntentLabel = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=64, strict=True)
]


class CheckpointRoute(PlannerRoute):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent: IntentLabel


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
