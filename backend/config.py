from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    app_env: str = "demo"
    llm_enabled: bool = False
    interactive_entry_enabled: bool = False
    # The conversation entry is its own switch. C0's answer contract ships on the
    # legacy endpoint, so enabling it must not depend on this flag, and turning
    # this on must not change any existing route.
    coach_conversations_enabled: bool = False
    coach_agent_mode: Literal['legacy', 'unified'] = 'legacy'
    entry_task_ttl_days: int = Field(default=30, gt=0)
    # Plan tasks and their candidates expire independently: a task lives for a
    # month, a candidate is only confirmable for half an hour. Confirmation
    # re-checks the snapshot it was shown, so a longer candidate life would widen
    # the window between "the user saw this" and "this is what gets written".
    plan_adjustment_task_ttl_days: int = Field(default=30, gt=0)
    plan_candidate_ttl_minutes: int = Field(default=30, gt=0)
    # Plan tasks are a delivery, not an experiment, so the entry is on by default:
    # shipping a feature nobody can open and calling it done is how the last three
    # checkpoints ended up invisible. Storage is a different decision -- see
    # ``plan_storage_mode`` -- and stays a data migration behind an explicit import.
    plan_adjustment_tasks_enabled: bool = True
    # Which store is the plan authority. This is a data-migration switch, not a
    # feature flag: turning the coach on must not move anybody's history, and a
    # merge must never migrate a database as a side effect. ``sqlite`` is refused
    # until an import has completed against the configured data directory.
    plan_storage_mode: Literal['file', 'sqlite'] = 'file'
    # Which side of the S4 paired comparison this deployment runs. It stays
    # "reference" even after the unified coach became the default path: flipping
    # it would delete the baseline the optimisation is measured against. The
    # visibility switch and the experiment variable are separate decisions.
    task_execution_strategy: Literal['reference', 'optimized'] = 'reference'
    # Which context policy is running. The value is recorded in the treatment
    # fingerprint, so it must name the code that actually ran; a mismatch is
    # refused at composition time rather than reported as a different policy.
    context_policy_version: str = 'context-policy-v1'
    # Whether a trusted shortcut may prefetch the published skill it needs. It
    # only takes effect on the optimized side: the reference side is the
    # baseline and must stay free of the thing being measured.
    prefetch_enabled: bool = True
    # A versioned result cache exists (``infrastructure/agent_runtime/task_cache``)
    # but is not wired into any request path: measured cold/hot on the seams it
    # could serve, it saved 0.01-0.12 ms per call and made a 5-56 KiB candidate
    # document 3-4x slower to read, because copying the value costs more than
    # decoding it. The flag is recorded so the treatment fingerprint states the
    # absence explicitly instead of reporting it as unknown.
    task_cache_enabled: bool = False
    agent_runtime_policy: dict[str, object] = Field(default_factory=dict)
    # How the semantic review treats an answer. "off" makes no extra call, which is the
    # default because it costs one provider request per answer. "shadow" records what it
    # would have decided without changing the answer; "enforce" lets a refusal tighten
    # the disposition. The deployment chooses; the code does not assume.
    safety_review_mode: Literal["off", "shadow", "enforce"] = "off"
    # How numeric claims are checked. "legacy" keeps the heuristic that compares the
    # draft's figures against every number in the tool results - a bare number is not
    # evidence, so it cannot tell a weight from a protein intake or one day from
    # another. "evidence" renders the figures from a metric/unit/scope catalog instead,
    # for the two intents that have one. Deployments move when they have chosen.
    safety_grounding_mode: Literal["legacy", "evidence"] = "legacy"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-5.5"
    embedding_model: str = "text-embedding-3-small"
    auth_secret: str = "fitlife-agent-demo-secret"
    settings_encryption_key: str | None = None
    backend_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    data_dir: Path = BACKEND_ROOT / "data"
    sqlite_database_path: Path | None = None
    knowledge_base_dir: Path = BACKEND_ROOT / "knowledge_base"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("sqlite_database_path", mode="before")
    @classmethod
    def blank_sqlite_database_path_uses_default(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @property
    def vector_index_path(self) -> Path:
        return self.data_dir / "vector_index.json"

    @property
    def database_path(self) -> Path:
        return self.sqlite_database_path or self.data_dir / "fitlife.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()
