from copy import deepcopy

from backend.configuration.models import EffectiveRunConfig, RequestOverrides, RuntimePolicy
from backend.configuration.store import MemoryPolicyStore


def _merge(base, patch):
    result = deepcopy(base)
    for name, value in patch.items():
        result[name] = _merge(result.get(name, {}), value) if isinstance(value, dict) else value
    return result


class ConfigurationResolver:
    def __init__(self, *, store=None, environment=None, routes=None):
        self.store = store or MemoryPolicyStore()
        self.environment = RuntimePolicy.model_validate(environment or {}).model_dump()
        self.routes = {}
        for operation, patch in (routes or {}).items():
            RuntimePolicy.model_validate(_merge(self.environment, patch))
            self.routes[operation] = deepcopy(patch)

    def resolve(self, operation, user_id, request_overrides=None):
        emergency = self.store.read()
        data = _merge(self.environment, self.routes.get(operation, {}))
        # Budget limits are safety constraints: even higher-precedence scopes
        # cannot relax a stricter lower-scope limit.
        for key, value in self.environment["budget"].items():
            data["budget"][key] = min(data["budget"][key], value)
        overrides = RequestOverrides.model_validate(request_overrides or {}).model_dump(exclude_none=True)
        if "deadline_seconds" in overrides:
            data["deadline_seconds"] = overrides.pop("deadline_seconds")
        for key, value in overrides.items():
            data["budget"][key] = min(data["budget"][key], value)
        # Emergency policy publication only tightens limits from lower scopes.
        if emergency.revision:
            limits = emergency.policy.model_dump()
            for name in ("budget", "rate_limit", "evaluation", "retry"):
                for key, value in limits[name].items():
                    data[name][key] = min(data[name][key], value)
            data["deadline_seconds"] = min(data["deadline_seconds"], limits["deadline_seconds"])
            data["max_completed_runs"] = min(data["max_completed_runs"], limits["max_completed_runs"])
        for key, ceiling in {"max_input_chars": 8000, "max_tokens": 32000, "max_model_calls": 16, "max_tool_calls": 32}.items():
            data["budget"][key] = min(data["budget"][key], ceiling)
        return EffectiveRunConfig(revision=emergency.revision, policy=RuntimePolicy.model_validate(data))
