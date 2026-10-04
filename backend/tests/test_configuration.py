import pytest
from pydantic import ValidationError

from backend.configuration.resolver import ConfigurationResolver
from backend.configuration.store import MemoryPolicyStore


def test_policy_publish_is_atomic_and_failed_update_preserves_last_good_snapshot():
    store = MemoryPolicyStore()
    resolver = ConfigurationResolver(store=store)
    store.publish({"deadline_seconds": 20.0})
    first = resolver.resolve("chat", "u")
    with pytest.raises(ValueError):
        store.publish({"deadline_seconds": -1.0, "api_key": "sk-secret"})
    assert resolver.resolve("chat", "u") == first
    assert "sk-secret" not in repr(store.diagnostics.entries)
    store.publish({"deadline_seconds": 10.0})
    assert first.policy.deadline_seconds == 20.0
    assert resolver.resolve("chat", "u").revision == first.revision + 1
    with pytest.raises(ValidationError):
        first.policy.deadline_seconds = 50.0


def test_precedence_and_code_ceiling_cannot_be_overridden():
    store = MemoryPolicyStore()
    resolver = ConfigurationResolver(store=store, environment={"deadline_seconds": 50.0}, routes={"chat": {"deadline_seconds": 40.0}})
    assert resolver.resolve("chat", "u").policy.deadline_seconds == 40.0
    assert resolver.resolve("chat", "u", {"deadline_seconds": 30.0}).policy.deadline_seconds == 30.0
    store.publish({"deadline_seconds": 20.0, "budget": {"max_tokens": 2000}})
    config = resolver.resolve("chat", "u", {"deadline_seconds": 100.0, "max_tokens": 100000})
    assert config.policy.deadline_seconds == 20.0
    assert config.policy.budget.max_tokens == 2000
    assert ConfigurationResolver().resolve("chat", "u", {"max_tokens": 999999}).policy.budget.max_tokens == 32000


@pytest.mark.parametrize("patch", [{"deadline_seconds": float("nan")}, {"max_tokens": -1}, {"max_tokens": "3"}, {"safety_enabled": False}, {"retry": {"max_retries": 0}}])
def test_invalid_request_overrides_are_rejected(patch):
    with pytest.raises(ValueError):
        ConfigurationResolver().resolve("chat", "u", patch)


def test_running_requests_keep_their_own_policy_when_reload_occurs():
    import asyncio
    import json
    from backend.agent.runtime import AgentRuntime
    from backend.agent.contracts import AgentCommand, AgentResult
    from backend.agent.telemetry import InMemoryTelemetryContext

    async def scenario():
        store = MemoryPolicyStore()
        telemetry = InMemoryTelemetryContext()
        runtime = AgentRuntime(resolver=ConfigurationResolver(store=store), telemetry=telemetry)
        started, release = asyncio.Event(), asyncio.Event()
        observed = []
        class Workflow:
            async def execute(self, command, context):
                if command.question == "first":
                    started.set()
                    await release.wait()
                observed.append((command.question, context.policy.deadline_seconds))
                return AgentResult("safe answer", "knowledge_qa", {}, {}, (), "mock")
        first = asyncio.create_task(runtime.execute(AgentCommand("chat", "first", "u"), Workflow()))
        await started.wait()
        store.publish({"deadline_seconds": 15.0})
        second = await runtime.execute(AgentCommand("chat", "second", "u"), Workflow())
        release.set()
        first = await first
        snapshots = [await runtime.get_status(item.run_id, "u") for item in (first, second)]
        assert observed == [("second", 15.0), ("first", 60.0)]
        assert [json.loads(item.policy_snapshot_json)["revision"] for item in snapshots] == [0, 1]
        assert [item.policy_version for item in snapshots] == ["policy-0", "policy-1"]
        assert [span.attributes["policy_version"] for span in telemetry.spans if span.name == "fitlife.agent.run"] == ["policy-0", "policy-1"]
    asyncio.run(scenario())


def test_model_connection_metadata_never_includes_endpoint_or_credentials():
    from backend.configuration.models import EffectiveRunConfig
    config = ConfigurationResolver().resolve("chat", "u")
    assert set(config.model_dump()) == {"revision", "policy"}
    for field in ("provider", "model", "encrypted_api_key", "base_url"):
        with pytest.raises(ValidationError):
            EffectiveRunConfig.model_validate({**config.model_dump(), field: "sk-secret"})


def test_factory_policy_resolution_does_not_read_user_connections(tmp_path, monkeypatch, isolated_agent_runtime):
    from backend.config import Settings
    from backend.infrastructure.agent_runtime import factory
    from backend.infrastructure.settings.file_model_connection_repository import FileModelConnectionRepository
    reads = []
    monkeypatch.setattr(FileModelConnectionRepository, "get", lambda self, user_id: reads.append(user_id))
    monkeypatch.setattr(factory, "get_settings", lambda: Settings(data_dir=tmp_path))
    runtime = isolated_agent_runtime()
    runtime.resolver.resolve("chat", "u")
    assert reads == []


def test_character_limit_is_question_only_but_context_still_consumes_tokens():
    import asyncio
    from backend.agent.runtime import AgentRuntime
    from backend.agent.contracts import AgentCommand, AgentResult
    class Workflow:
        async def execute(self, command, context):
            assert context.input_chars == len(command.question)
            assert context.tokens > 2000
            return AgentResult("safe", "knowledge_qa", {}, {}, (), "mock")
    outcome = asyncio.run(AgentRuntime().execute(AgentCommand("chat", "hello", "u", initial_tool_results={"context": "x" * 10000}), Workflow()))
    assert outcome.status == "succeeded"


def test_concurrent_publications_have_atomic_unique_revisions():
    from concurrent.futures import ThreadPoolExecutor
    store = MemoryPolicyStore()
    with ThreadPoolExecutor(max_workers=4) as pool:
        revisions = list(pool.map(lambda n: store.publish({"deadline_seconds": float(n + 1)}).revision, range(20)))
    assert sorted(revisions) == list(range(1, 21))
    assert store.read().revision == 20


def test_factory_loads_environment_defaults_and_persists_revision(tmp_path, monkeypatch, isolated_agent_runtime):
    import json
    from backend.config import Settings
    from backend.agent.contracts import AgentCommand, AgentResult
    from backend.infrastructure.agent_runtime import factory
    monkeypatch.setattr(factory, "get_settings", lambda: Settings(data_dir=tmp_path, agent_runtime_policy={"deadline_seconds": 25.0}))
    runtime = isolated_agent_runtime()
    runtime.resolver.store.publish({"deadline_seconds": 12.0})
    class Workflow:
        async def execute(self, command, context):
            assert context.policy.deadline_seconds == 12.0
            return AgentResult("ok", "knowledge_qa", {}, {}, (), "mock")
    outcome = runtime.execute_sync(AgentCommand("chat", "hello", "u"), Workflow())
    snapshot = runtime.repository.get(outcome.run_id, "u")
    assert json.loads(snapshot.policy_snapshot_json)["revision"] == 1


def test_request_configuration_failure_is_persisted_without_invalid_values():
    from backend.agent.runtime import AgentRuntime
    from backend.agent.contracts import AgentCommand
    from backend.domain.errors import ApplicationError
    runtime = AgentRuntime()
    with pytest.raises(ApplicationError) as failure:
        runtime.execute_sync(AgentCommand("chat", "hello", "u", request_overrides={"secret": "sk-private"}), None)
    error = failure.value
    assert error.code == "CONFIGURATION_INVALID"
    assert error.request_id and error.run_id
    snapshot = runtime.repository.get(error.run_id, "u")
    assert snapshot.public_error_code == "CONFIGURATION_INVALID"
    assert "sk-private" not in repr(snapshot)


def test_unvalidated_model_copy_cannot_bypass_publish_validation():
    from backend.configuration.models import RuntimePolicy
    store = MemoryPolicyStore()
    with pytest.raises(ValueError):
        store.publish(RuntimePolicy().model_copy(update={"deadline_seconds": float("inf")}))
    assert store.read().revision == 0


def test_request_cannot_relax_a_stricter_route_budget():
    resolver = ConfigurationResolver(routes={"chat": {"budget": {"max_tokens": 1000}}})
    assert resolver.resolve("chat", "u", {"max_tokens": 2000}).policy.budget.max_tokens == 1000


@pytest.mark.parametrize("source", ["environment", "publication"])
@pytest.mark.parametrize("fails", [False, True])
def test_effective_zero_retention_evicts_completed_runs_but_preserves_history(source, fails, tmp_path):
    import asyncio
    import json
    from backend.agent.contracts import AgentCommand, AgentResult
    from backend.agent.runtime import AgentRuntime
    from backend.infrastructure.agent_runtime.sqlite_run_repository import SQLiteRunRepository
    store = MemoryPolicyStore()
    environment = {"max_completed_runs": 0} if source == "environment" else {}
    runtime = AgentRuntime(resolver=ConfigurationResolver(store=store, environment=environment),
                           repository=SQLiteRunRepository(tmp_path / "retention.sqlite3"))
    if source == "publication":
        store.publish({"max_completed_runs": 0})
    class Workflow:
        async def execute(self, command, context):
            if fails:
                raise ValueError("workflow failed")
            return AgentResult("ok", "knowledge_qa", {}, {}, (), "mock")
    command = AgentCommand("chat", "hello", "u")
    if fails:
        with pytest.raises(ValueError) as failure:
            runtime.execute_sync(command, Workflow())
        run_id = failure.value.run_id
    else:
        run_id = runtime.execute_sync(command, Workflow()).run_id
    assert runtime._runs == {}
    assert runtime.active_run_ids == ()
    snapshot = asyncio.run(runtime.get_status(run_id, "u"))
    assert snapshot.status == ("failed" if fails else "succeeded")
    assert json.loads(snapshot.policy_snapshot_json)["policy"]["max_completed_runs"] == 0
