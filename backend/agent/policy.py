from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    jitter_ratio: float = 0.2

    @property
    def max_attempts(self) -> int:
        return self.max_retries + 1

    def delay_seconds(self, retry_number: int, *, retry_after: float | None = None, random_value: float = 0.5) -> float:
        exponential = self.base_delay_seconds * (2 ** max(0, retry_number - 1))
        jitter = exponential * self.jitter_ratio * ((random_value * 2) - 1)
        calculated = max(0.0, exponential + jitter)
        requested = max(calculated, max(0.0, retry_after or 0.0))
        return min(self.max_delay_seconds, requested)


@dataclass(frozen=True)
class BudgetPolicy:
    max_input_chars: int = 8_000
    max_tokens: int = 32_000
    max_model_calls: int = 16
    max_tool_calls: int = 32


@dataclass(frozen=True)
class RuntimePolicy:
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    budget: BudgetPolicy = field(default_factory=BudgetPolicy)
    deadline_seconds: float = 60.0
