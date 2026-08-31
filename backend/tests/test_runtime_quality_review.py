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


def test_public_run_status_and_terminal_cancel_endpoints():
    class Workflow:
        async def execute(self, command, context):
            return AgentResult("ok", "knowledge_qa", {}, {}, (), "model")
    outcome = asyncio.run(DEFAULT_AGENT_RUNTIME.execute(AgentCommand("chat", "hello", None), Workflow()))
    client = TestClient(app)

    status = client.get(f"/agent/runs/{outcome.run_id}")
    cancelled = client.post(f"/agent/runs/{outcome.run_id}/cancel")
    missing = client.get("/agent/runs/missing")

    assert status.status_code == 200
    assert status.json()["data"]["status"] == "succeeded"
    assert cancelled.json()["data"] == {"run_id": outcome.run_id, "cancelled": False, "status": "succeeded"}
    assert missing.status_code == 404
    assert missing.json()["error"]["run_id"] == "missing"


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
