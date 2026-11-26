"""Versioned planner & workflow step recovery boundaries; validated shapes only."""
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from backend.agent.route_contract import PlannerRoute

DomainName = Literal["profile", "training", "diet"]
CheckpointId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,64}$", strict=True)]
ToolNameStr = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.]*$", max_length=64, strict=True)]

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


class CachedToolObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    call_id: CheckpointId
    tool: ToolNameStr
    arguments: dict[str, Any]
    observation: dict[str, Any]
    required_domains: list[DomainName] = Field(default_factory=list)
    source_version: str | int | None = None


class WorkflowStepCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[2]
    stage: Literal["tool_round", "pre_review"]
    step_index: int = Field(ge=0, le=128)
    principal_owner_id: str = Field(max_length=128)
    authorized_domains: list[DomainName] = Field(default_factory=list)
    policy_version: str = Field(min_length=1, max_length=128)
    completed_steps: list[str] = Field(default_factory=list, max_length=64)
    dependency_versions: dict[str, str] = Field(default_factory=dict)
    cached_tool_calls: list[CachedToolObservation] = Field(default_factory=list, max_length=32)


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


def restore_workflow_checkpoint(checkpoint: dict) -> WorkflowStepCheckpoint:
    """Validate and reconstruct a step-level unified workflow recovery boundary."""
    if type(checkpoint.get("schema_version")) is not int:
        raise ValueError("Invalid checkpoint schema version")
    return WorkflowStepCheckpoint.model_validate(checkpoint)
