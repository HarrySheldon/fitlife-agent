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
        "run_id": result.run_id,
    }


def test_runtime_uses_caller_request_id_but_generates_one_when_absent():
    supplied = asyncio.run(AgentRuntime().execute(
        AgentCommand(operation="chat", question="hello", user_id=None, request_id="http-request"),
        RecordingWorkflow(),
    ))
    generated = asyncio.run(AgentRuntime().execute(
        AgentCommand(operation="chat", question="hello", user_id=None), RecordingWorkflow()
    ))

    assert supplied.request_id == "http-request"
    assert supplied.result.request_id == "http-request"
    assert supplied.run_id == supplied.result.run_id
    assert generated.request_id
    assert generated.request_id != "http-request"


def test_sync_runtime_bridge_is_safe_inside_an_existing_event_loop():
    async def call_sync_api() -> AgentResult:
        return AgentRuntime().execute_sync(
            AgentCommand(operation="chat", question="inside loop", user_id=None),
            RecordingWorkflow(),
        )

    result = asyncio.run(call_sync_api())

    assert result.answer_markdown == "INSIDE LOOP"


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


def test_reused_workflow_gives_each_run_an_independent_nested_context_snapshot():
    metadata = {"preferences": {"language": "zh-CN"}}

    class MutatingGateway(Gateway):
        observed_languages: list[str] = []

        def write_answer(self, state: dict) -> str:
            preferences = state["context_metadata"]["preferences"]
            self.observed_languages.append(preferences["language"])
            preferences["language"] = "polluted"
            return "answer"

    gateway = MutatingGateway(needs_retrieval=False)
    workflow = FitLifeWorkflow(FileFitnessRepository(), gateway, context_metadata=metadata)
    metadata["preferences"]["language"] = "externally-mutated"

    asyncio.run(workflow.execute(AgentCommand("chat", "first", None), RuntimeContext()))
    asyncio.run(workflow.execute(AgentCommand("chat", "second", None), RuntimeContext()))

    assert gateway.observed_languages == ["zh-CN", "zh-CN"]


def test_explicit_workflow_records_named_runtime_tools_and_replay_policies():
    class ObservingContext(RuntimeContext):
        def __init__(self) -> None:
            super().__init__()
            self.tool_invocations: list[tuple[str, str]] = []

        async def tool(self, name: str, replay: str, operation):
            self.tool_invocations.append((name, replay))
            return await super().tool(name, replay, operation)

    class PlanningGateway(Gateway):
        def plan_route(self, question: str) -> PlannerRoute:
            return PlannerRoute(
                intent="plan_generation",
                needs_meal_analysis=True,
                needs_workout_analysis=True,
                needs_retrieval=True,
                needs_plan=True,
            )

    context = ObservingContext()
    workflow = FitLifeWorkflow(FileFitnessRepository(), PlanningGateway(needs_retrieval=True))

    asyncio.run(workflow.execute(AgentCommand("chat", "plan with meals and workouts", None), context))

    assert context.tool_invocations == [
        ("plan_route_model", "safe"),
        ("load_profile", "safe"),
        ("analyze_meals", "safe"),
        ("analyze_workouts", "safe"),
        ("retrieve_knowledge", "safe"),
        ("generate_next_week_plan", "safe"),
        ("validate_plan", "safe"),
        ("write_answer_model", "safe"),
    ]
    assert context.completed_tools == [name for name, _ in context.tool_invocations]


def test_runtime_context_exposes_the_phase_one_tool_execution_path():
    context = RuntimeContext()

    value = asyncio.run(context.tool("load_profile", "safe", lambda: {"goal": "maintenance"}))

    assert value == {"goal": "maintenance"}
    assert context.completed_tools == ["load_profile"]
