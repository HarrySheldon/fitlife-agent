"""One lazily assembled runtime per effective deployment data directory."""
from pathlib import Path
from threading import RLock

from backend.config import get_settings
from backend.agent.runtime import AgentRuntime
from backend.infrastructure.agent_runtime.sqlite_run_repository import SQLiteRunRepository
from backend.infrastructure.agent_runtime.sqlite_checkpoint_store import SQLiteCheckpointStore
from backend.configuration.resolver import ConfigurationResolver
from backend.configuration.store import MemoryPolicyStore

_runtime = None
_path = None
_lock = RLock()


def get_agent_runtime():
    global _runtime, _path
    path = (Path(get_settings().data_dir) / "agent_runtime.sqlite3").resolve()
    with _lock:
        if _runtime is None or path != _path:
            repository = SQLiteRunRepository(path)
            resolver = ConfigurationResolver(store=MemoryPolicyStore(), environment=get_settings().agent_runtime_policy)
            _runtime = AgentRuntime(repository=repository, checkpoint_store=SQLiteCheckpointStore(repository), resolver=resolver)
            _path = path
        return _runtime


class CurrentAgentRuntime:
    """Compatibility handle resolves current settings without another runtime."""
    def __getattr__(self, name):
        return getattr(get_agent_runtime(), name)
