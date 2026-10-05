"""The planner boundary must tolerate how a real model actually classifies.

A live provider returns free-form intent labels ("nutrition_analysis",
"meal_summary", "fat_loss_training_plan"). Bounded storage shape may be enforced,
but an off-taxonomy label must never abort a run: the routing flags drive the
workflow, and the label is only carried for the trace and the deterministic writer.

A checkpoint is a durability aid. Losing a checkpoint may cost recovery, it must
never cost the answer.
"""
import asyncio

import pytest

from backend.agent.contracts import AgentCommand
from backend.agent.persistence import InvalidTransition
from backend.agent.planner import PlannerRoute
from backend.agent.runtime import AgentRuntime
from backend.agent.workflow import FitLifeWorkflow, rebuild_state_after_planner
from backend.infrastructure.agent_runtime.memory_run_repository import (
    MemoryCheckpointStore,
    MemoryRunRepository,
)
from backend.infrastructure.repositories.file_fitness_repository import FileFitnessRepository


# Labels a real model produced for this project's own questions.
REAL_MODEL_INTENTS = (
    "nutrition_analysis",
    "meal_summary",
    "workout_progress_comparison",
    "nutrition_advice",
    "fat_loss_training_plan",
    "find_highest_calorie_food",
    "meal_planning",
    "general_fitness_question",
)


class FreeFormIntentGateway:
    """A gateway that classifies the way a live provider does."""

    model = "test-model"

    def __init__(self, intent: str) -> None:
        self.intent = intent

    def plan_route(self, question):
        return PlannerRoute(intent=self.intent, needs_meal_analysis=True)

    def write_answer(self, state):
        return "private response"


@pytest.mark.parametrize("intent", REAL_MODEL_INTENTS)
def test_off_taxonomy_intent_does_not_abort_the_run(intent):
    """The exact production failure: a good plan was thrown away by storage."""
    repository = MemoryRunRepository()
    command = AgentCommand("chat", "private question", None)
    workflow = FitLifeWorkflow(
        FileFitnessRepository(),
        FreeFormIntentGateway(intent),
        retriever=lambda *_: [],
    )

    outcome = asyncio.run(
        AgentRuntime(repository=repository, checkpoint_store=MemoryCheckpointStore(repository)).execute(
            command, workflow
        )
    )

    assert outcome.status == "succeeded"
    assert outcome.intent == intent


@pytest.mark.parametrize("intent", REAL_MODEL_INTENTS)
def test_off_taxonomy_intent_survives_the_planner_boundary(intent):
    """A stored boundary must round-trip a real classification label."""
    route = PlannerRoute(intent=intent, needs_meal_analysis=True)
    payload = {"schema_version": 1, "next_step": "profile_loader", "route": route.model_dump()}

    state = rebuild_state_after_planner(AgentCommand("chat", "q", "u"), payload)

    assert state["intent"] == intent
    assert PlannerRoute.model_validate(state["tool_requests"]) == route


def test_unavailable_checkpoint_storage_does_not_abort_the_run():
    """Checkpointing is an aid; its absence must cost recovery, not the answer."""
    repository = MemoryRunRepository()
    command = AgentCommand("chat", "private question", None)
    workflow = FitLifeWorkflow(
        FileFitnessRepository(),
        FreeFormIntentGateway("meal_analysis"),
        retriever=lambda *_: [],
    )

    # checkpoint_store omitted -> the runtime has no place to persist boundaries.
    runtime = AgentRuntime(repository=repository)
    outcome = asyncio.run(runtime.execute(command, workflow))

    assert outcome.status == "succeeded"


def test_failing_checkpoint_write_does_not_abort_the_run():
    """A storage write failure is reported, not raised into the pipeline."""
    repository = MemoryRunRepository()

    class BrokenCheckpoints(MemoryCheckpointStore):
        def save(self, run_id, user_id, name, state):
            raise InvalidTransition("checkpoint storage is full")

    command = AgentCommand("chat", "private question", None)
    workflow = FitLifeWorkflow(
        FileFitnessRepository(),
        FreeFormIntentGateway("meal_analysis"),
        retriever=lambda *_: [],
    )

    runtime = AgentRuntime(repository=repository, checkpoint_store=BrokenCheckpoints(repository))
    outcome = asyncio.run(runtime.execute(command, workflow))

    assert outcome.status == "succeeded"
    payloads = [event.payload for event in repository.events(outcome.run_id, None)]
    assert any(payload.get("error_code") == "CHECKPOINT_UNAVAILABLE" for payload in payloads)
