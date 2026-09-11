import asyncio
from copy import deepcopy

import pytest

from backend.agent.contracts import AgentCommand, AgentRunSnapshot
from backend.agent.persistence import InvalidTransition
from backend.agent.planner import PlannerRoute
from backend.agent.runtime import AgentRuntime
from backend.agent.workflow import FitLifeWorkflow, rebuild_state_after_planner
from backend.infrastructure.agent_runtime.memory_run_repository import MemoryRunRepository, MemoryCheckpointStore
from backend.infrastructure.agent_runtime.sqlite_run_repository import SQLiteRunRepository
from backend.infrastructure.agent_runtime.sqlite_checkpoint_store import SQLiteCheckpointStore
from backend.infrastructure.repositories.file_fitness_repository import FileFitnessRepository


@pytest.fixture(params=["memory", "sqlite"])
def stores(request, tmp_path):
    if request.param == "memory":
        repository = MemoryRunRepository()
        return repository, MemoryCheckpointStore(repository), lambda: MemoryCheckpointStore(repository)
    path = tmp_path / "checkpoint.sqlite3"
    repository = SQLiteRunRepository(path)
    return repository, SQLiteCheckpointStore(repository), lambda: SQLiteCheckpointStore(SQLiteRunRepository(path))


class Gateway:
    model = "test-model"

    def plan_route(self, question):
        return PlannerRoute(intent="knowledge_qa", needs_retrieval=True)

    def write_answer(self, state):
        return "private response"


def test_real_workflow_persists_reconstructable_planner_boundary(stores):
    repository, store, reopen = stores
    command = AgentCommand("chat", "private question", None)
    workflow = FitLifeWorkflow(FileFitnessRepository(), Gateway(), retriever=lambda *_: [])
    outcome = asyncio.run(AgentRuntime(repository=repository, checkpoint_store=store).execute(command, workflow))
    saved = reopen().get(outcome.run_id, None, "planner")
    assert saved.state["next_step"] == "profile_loader"
    state = rebuild_state_after_planner(command, saved.state)
    assert state["user_query"] == command.question
    assert PlannerRoute.model_validate(state["tool_requests"]) == Gateway().plan_route("")
    assert not {"profile", "final_answer", "validation_result"} & state.keys()
    assert "private" not in repr(saved)
    assert all(not {"route", "schema_version", "next_step"} & event.payload.keys()
               for event in repository.events(outcome.run_id, None))
    assert "schema_version" not in repr(outcome.trace)
    saved.state["route"]["intent"] = "private mutation"
    assert reopen().get(outcome.run_id, None, "planner").state["route"]["intent"] == "knowledge_qa"
    with pytest.raises(KeyError):
        reopen().get(outcome.run_id, "other-user", "planner")
    with pytest.raises(KeyError):
        store.save(outcome.run_id, "other-user", "planner", reopen().get(outcome.run_id, None, "planner").state)
    with pytest.raises(InvalidTransition):
        store.save(outcome.run_id, None, "planner", reopen().get(outcome.run_id, None, "planner").state)


@pytest.mark.parametrize("bad", [
    {"question": "secret"}, {"health": {}}, {"prompt": "secret"}, {"response": "secret"},
    {"schema_version": True}, {"schema_version": 2}, {"next_step": "writer"},
    {"route": {"intent": "private text"}},
    {"route": {"intent": "knowledge_qa", "needs_plan": "true"}},
    {"route": {"intent": "knowledge_qa", "unknown": "secret"}},
])
def test_store_and_reconstruction_reject_non_whitelisted_state(stores, bad):
    repository, store, _ = stores
    repository.create(AgentRunSnapshot("r", "q", "u", "chat", "accepted"))
    payload = {"schema_version": 1, "next_step": "profile_loader", "route": Gateway().plan_route("").model_dump()}
    payload.update(deepcopy(bad))
    with pytest.raises(ValueError):
        store.save("r", "u", "planner", payload)
    with pytest.raises(ValueError):
        rebuild_state_after_planner(AgentCommand("chat", "q", "u"), payload)
