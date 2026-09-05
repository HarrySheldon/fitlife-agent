import asyncio
from threading import Thread, Event

from fastapi.testclient import TestClient

from backend.agent.contracts import AgentCommand
from backend.agent.runtime import AgentRuntime
from backend.agent.runtime import BudgetExceeded
from backend.agent.policy import BudgetPolicy, RuntimePolicy
from backend.domain.errors import model_gateway_error
from backend.main import app
from backend.agent.graph import DEFAULT_AGENT_RUNTIME
from backend.agent.contracts import AgentResult
from backend.agent.workflow import FitLifeWorkflow
from backend.agent.planner import PlannerRoute
from backend.infrastructure.repositories.file_fitness_repository import FileFitnessRepository
from backend.agent.model_payloads import incremental_writer_payload, serialized_payload, writer_payload


class ProviderApiError(Exception):
    def __init__(self, status_code, code=""):
        self.status_code = status_code
        self.code = code


def test_provider_errors_use_status_and_code_not_exception_class_name():
    rate = model_gateway_error(ProviderApiError(429))
    auth = model_gateway_error(ProviderApiError(401))
    missing = model_gateway_error(ProviderApiError(404, "model_not_found"))

    assert (rate.code, rate.status_code, rate.retryable) == ("MODEL_RATE_LIMITED", 429, True)
    assert (auth.code, auth.status_code, auth.retryable) == ("MODEL_AUTH_FAILED", 502, False)
    assert (missing.code, missing.status_code, missing.retryable) == ("MODEL_NOT_FOUND", 422, False)


def test_openapi_retains_api_error_component_name():
    schema = app.openapi()

    assert "ApiError" in schema["components"]["schemas"]
    assert set(schema["components"]["schemas"]["ApiError"]["properties"]) >= {
        "code", "message", "action", "retryable", "retry_after_ms", "request_id", "run_id"
    }


def test_large_initial_tool_result_is_rejected_before_workflow_execution():
    called = False
    class Workflow:
        async def execute(self, command, context):
            nonlocal called
            called = True

    runtime = AgentRuntime(policy=RuntimePolicy(budget=BudgetPolicy(
        max_input_chars=8_000, max_tokens=32_000, max_model_calls=16, max_tool_calls=32
    )))
    command = AgentCommand("chat", "short", None, initial_tool_results={"payload": "x" * 10_000})

    try:
        asyncio.run(runtime.execute(command, Workflow()))
        assert False, "budget must fail"
    except BudgetExceeded:
        pass
    assert called is False


def test_runtime_can_be_cancelled_and_queried_across_threads():
    started, release = Event(), Event()
    runtime = AgentRuntime()
    failure = []
    class Workflow:
        async def execute(self, command, context):
            started.set()
            await asyncio.to_thread(release.wait)
            context.raise_if_cancelled()
    def execute():
        try:
            asyncio.run(runtime.execute(AgentCommand("chat", "hello", "owner"), Workflow()))
        except Exception as error:
            failure.append(error)

    thread = Thread(target=execute); thread.start(); assert started.wait(2)
    run_id = runtime.active_run_ids[0]
    assert asyncio.run(runtime.cancel(run_id, "intruder")).status == "not_found"
    assert asyncio.run(runtime.cancel(run_id, "owner")).cancelled is True
    release.set(); thread.join(2)
    assert asyncio.run(runtime.get_status(run_id, "owner")).status == "cancelled"
    assert failure[0].run_id == run_id


def test_runtime_control_is_not_exposed_as_an_unusable_http_route():
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert not any(path.startswith("/agent/runs") for path in paths)


def test_workflow_retries_wrapped_provider_429_by_status_semantics():
    class Gateway:
        model = "model"
        attempts = 0
        def plan_route(self, question):
            self.attempts += 1
            if self.attempts < 3: raise ProviderApiError(429)
            return PlannerRoute(intent="knowledge_qa")
        def write_answer(self, state): return "ok"
    gateway = Gateway()

    outcome = asyncio.run(AgentRuntime().execute(
        AgentCommand("chat", "hello", None), FitLifeWorkflow(FileFitnessRepository(), gateway)
    ))

    assert outcome.status == "succeeded"
    assert gateway.attempts == 3


def test_wrapped_terminal_provider_errors_are_not_retried():
    for status, code in [(401, ""), (429, "insufficient_quota"), (404, "model_not_found")]:
        class Gateway:
            model = "model"; attempts = 0
            def plan_route(self, question):
                self.attempts += 1; raise ProviderApiError(status, code)
            def write_answer(self, state): return "never"
        gateway = Gateway()
        try: asyncio.run(AgentRuntime().execute(AgentCommand("chat", "hello", None), FitLifeWorkflow(FileFitnessRepository(), gateway)))
        except Exception: pass
        assert gateway.attempts == 1


def test_asyncio_cancellation_becomes_cancelled_snapshot():
    class Workflow:
        async def execute(self, command, context): raise asyncio.CancelledError()
    runtime = AgentRuntime()
    try: asyncio.run(runtime.execute(AgentCommand("chat", "hello", None), Workflow()))
    except Exception as error: run_id = error.run_id
    assert asyncio.run(runtime.get_status(run_id, None)).status == "cancelled"
    assert run_id not in runtime.active_run_ids


def test_completed_snapshots_are_bounded_without_evicting_active():
    class Workflow:
        async def execute(self, command, context): return AgentResult("ok", "x", {}, {}, (), "m")
    runtime = AgentRuntime(policy=RuntimePolicy(max_completed_runs=2))
    ids = [asyncio.run(runtime.execute(AgentCommand("chat", str(i), None), Workflow())).run_id for i in range(3)]
    try: asyncio.run(runtime.get_status(ids[0], None)); assert False
    except KeyError: pass
    assert asyncio.run(runtime.get_status(ids[-1], None)).status == "succeeded"


def test_writer_budget_payload_matches_adapter_and_counts_replaced_initial_value():
    initial = {"report": "small"}
    state = {"user_query": "q", "context_metadata": {}, "intent": "x", "profile": {},
             "tool_results": {"report": "x" * 10_000}, "retrieved_docs": [], "validation_result": {}}
    incremental = incremental_writer_payload(state, initial)

    assert writer_payload(state)["tool_results"]["report"] == "x" * 10_000
    assert incremental["tool_results"]["report"] == "x" * 10_000
    assert len(serialized_payload(incremental)) > 10_000
    state["tool_results"] = initial
    assert incremental_writer_payload(state, initial)["tool_results"] == {}
