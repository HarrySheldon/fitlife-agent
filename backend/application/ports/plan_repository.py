from __future__ import annotations

from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict

from backend.schemas import GeneratedPlan


PlanKind = Literal["deterministic", "agent_adjusted"]


class StoredPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan_id: str
    activated_at: AwareDatetime
    kind: PlanKind
    based_on_plan_id: str | None = None
    plan: GeneratedPlan


class StoredPlanDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    draft_id: str
    created_at: AwareDatetime
    kind: PlanKind
    based_on_plan_id: str | None = None
    plan: GeneratedPlan


class PlanRepository(Protocol):
    def save(self, user_id: str, plan: StoredPlan) -> None: ...

    def list(self, user_id: str) -> list[StoredPlan]: ...

    def get(self, user_id: str, plan_id: str) -> StoredPlan | None: ...

    def save_draft(self, user_id: str, draft: StoredPlanDraft) -> None: ...

    def get_draft(self, user_id: str, draft_id: str) -> StoredPlanDraft | None: ...

    def take_draft(self, user_id: str, draft_id: str) -> StoredPlanDraft | None: ...
