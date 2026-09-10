"""Keep the production runtime database out of repository sample data in tests."""
import pytest


@pytest.fixture(autouse=True)
def isolated_agent_runtime(monkeypatch):
    from backend.agent.runtime import AgentRuntime
    from backend.infrastructure.agent_runtime import factory

    runtime = AgentRuntime()
    production_factory = factory.get_agent_runtime
    monkeypatch.setattr(factory, "get_agent_runtime", lambda: runtime)
    return production_factory
