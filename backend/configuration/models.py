from pydantic import BaseModel, ConfigDict, Field
from backend.agent.policy import RetryPolicy as ExecutionRetryPolicy


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False, revalidate_instances="always")


class RetryPolicy(StrictModel):
    max_retries: int = Field(default=3, ge=0, le=10)
    base_delay_seconds: float = Field(default=0.5, ge=0)
    max_delay_seconds: float = Field(default=8.0, ge=0)
    jitter_ratio: float = Field(default=0.2, ge=0, le=1)

    @property
    def max_attempts(self):
        return self.max_retries + 1

    def delay_seconds(self, *args, **kwargs):
        return ExecutionRetryPolicy(**self.model_dump()).delay_seconds(*args, **kwargs)


class BudgetPolicy(StrictModel):
    max_input_chars: int = Field(default=8000, ge=1)
    max_tokens: int = Field(default=32000, ge=1)
    max_model_calls: int = Field(default=16, ge=1)
    max_tool_calls: int = Field(default=32, ge=1)


class RateLimitPolicy(StrictModel):
    requests_per_minute: int = Field(default=60, ge=1)
    concurrent_runs: int = Field(default=4, ge=1)
    anonymous_requests_per_minute: int = Field(default=10, ge=1)
    anonymous_concurrent_runs: int = Field(default=1, ge=1)


class EvalPolicy(StrictModel):
    max_cases: int = Field(default=100, ge=1, le=1000)
    max_model_calls: int = Field(default=1600, ge=1)
    max_tokens: int = Field(default=3_200_000, ge=1)


class RuntimePolicy(StrictModel):
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    budget: BudgetPolicy = Field(default_factory=BudgetPolicy)
    rate_limit: RateLimitPolicy = Field(default_factory=RateLimitPolicy)
    evaluation: EvalPolicy = Field(default_factory=EvalPolicy)
    deadline_seconds: float = Field(default=60.0, gt=0, le=3600)
    max_completed_runs: int = Field(default=1000, ge=0, le=10000)


class RunPolicySnapshot(StrictModel):
    revision: int = Field(default=0, ge=0)
    policy: RuntimePolicy = Field(default_factory=RuntimePolicy)


class EffectiveRunConfig(RunPolicySnapshot):
    """Execution policy only; gateways resolve and record actual model metadata."""


class RequestOverrides(StrictModel):
    deadline_seconds: float | None = Field(default=None, gt=0, le=3600)
    max_tokens: int | None = Field(default=None, ge=1)
    max_model_calls: int | None = Field(default=None, ge=1)
    max_tool_calls: int | None = Field(default=None, ge=1)
