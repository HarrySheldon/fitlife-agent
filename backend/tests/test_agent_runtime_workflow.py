from __future__ import annotations

import asyncio

from backend.agent.contracts import AgentCommand, AgentResult
from backend.agent.runtime import AgentRuntime, RuntimeContext
from backend.agent.workflow import FitLifeWorkflow
from backend.infrastructure.repositories.file_fitness_repository import FileFitnessRepository
from backend.agent.planner import PlannerRoute


class RecordingWorkflow:
    async def execute(self, command: AgentCommand, context: RuntimeContext) -> AgentResult:
        value = await context.step("planner", lambda: command.question.upper())
        return AgentResult(
            answer_markdown=value,
            intent="knowledge_qa",
            trace={"tool_calls": []},
            tool_results={},
            sources=(),
            model="test-model",
        )


def test_runtime_executes_a_typed_command_and_projects_the_compatible_result():
    command = AgentCommand(operation="chat", question="hello", user_id="user-1")

    result = asyncio.run(AgentRuntime().execute(command, RecordingWorkflow()))

    assert result.answer_markdown == "HELLO"
    assert result.request_id
    assert result.to_dict() == {
        "answer_markdown": "HELLO",
        "intent": "knowledge_qa",
        "trace": {"tool_calls": []},
        "tool_results": {},
        "sources": [],
        "model": "test-model",
        "request_id": result.request_id,
    }


class Gateway:
    model = "test-model"

    def __init__(self, *, needs_retrieval: bool) -> None:
        self.needs_retrieval = needs_retrieval

    def plan_route(self, question: str) -> PlannerRoute:
        return PlannerRoute(intent="knowledge_qa", needs_retrieval=self.needs_retrieval)

    def write_answer(self, state: dict) -> str:
        return "answer"


def test_explicit_workflow_runs_steps_in_order_and_skips_unrequested_retrieval():
    context = RuntimeContext()
    workflow = FitLifeWorkflow(FileFitnessRepository(), Gateway(needs_retrieval=False))

    asyncio.run(workflow.execute(AgentCommand("chat", "hello", None), context))

    assert context.completed_steps == [
        "planner",
        "profile_loader",
        "data_analyzer",
        "deterministic_generator",
        "deterministic_validator",
        "writer",
        "result_projector",
    ]


def test_explicit_workflow_includes_retriever_when_planner_requests_it():
    context = RuntimeContext()
    workflow = FitLifeWorkflow(
        FileFitnessRepository(),
        Gateway(needs_retrieval=True),
        retriever=lambda query, top_k: [{"source": "test.md", "text": query}],
    )

    result = asyncio.run(workflow.execute(AgentCommand("evaluation", "hello", None), context))

    assert context.completed_steps[3] == "retriever"
    assert result.sources == ({"source": "test.md", "text": "hello"},)


def test_runtime_context_exposes_the_phase_one_tool_execution_path():
    context = RuntimeContext()

    value = asyncio.run(context.tool("load_profile", "safe", lambda: {"goal": "maintenance"}))

    assert value == {"goal": "maintenance"}
    assert context.completed_tools == ["load_profile"]
