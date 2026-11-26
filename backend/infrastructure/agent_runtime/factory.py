"""One lazily assembled runtime per effective PostgreSQL deployment target."""
from threading import RLock

from backend.agent.runtime import AgentRuntime
from backend.config import get_settings
from backend.configuration.resolver import ConfigurationResolver
from backend.configuration.store import MemoryPolicyStore
from backend.infrastructure.agent_runtime.postgres_checkpoint_store import (
    PostgresCheckpointStore,
)
from backend.infrastructure.agent_runtime.postgres_run_repository import (
    PostgresRunRepository,
)
from backend.infrastructure.observability.otel import build_telemetry_context
from backend.infrastructure.postgres.database import PostgresDatabase

_runtime = None
_target_key = None
_lock = RLock()


def get_agent_runtime():
    global _runtime, _target_key
    settings = get_settings()
    key = (
        settings.database_url,
        settings.database_schema or "public",
        settings.telemetry_exporter,
        settings.otel_service_name,
        settings.otel_exporter_otlp_endpoint,
        settings.langfuse_host,
    )
    with _lock:
        if _runtime is None or key != _target_key:
            database = PostgresDatabase(
                settings.database_url,
                schema=settings.database_schema,
            )
            repository = PostgresRunRepository(database)
            resolver = ConfigurationResolver(
                store=MemoryPolicyStore(),
                environment=settings.agent_runtime_policy,
            )
            telemetry = build_telemetry_context(settings)
            _runtime = AgentRuntime(
                repository=repository,
                checkpoint_store=PostgresCheckpointStore(repository),
                telemetry=telemetry,
                resolver=resolver,
            )
            _target_key = key
        return _runtime


class CurrentAgentRuntime:
    """Compatibility handle resolves current settings without another runtime."""

    def __getattr__(self, name):
        return getattr(get_agent_runtime(), name)
