from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from backend.application.ports.plan_repository import PlanKind, PlanRepository, StoredPlan, StoredPlanDraft
from backend.domain.errors import ApplicationError
from backend.schemas import ValidationResult


PlanDraft = StoredPlanDraft


class Plans:
    def __init__(
        self,
        repository: PlanRepository,
        generate_deterministic: Callable[[str], dict[str, Any]],
        generate_adjusted: Callable[[str, StoredPlan, str], dict[str, Any]],
        validate_plan: Callable[[str, dict[str, Any]], dict[str, Any]],
        *,
        now: Callable[[], datetime] | None = None,
        new_id: Callable[[], str] | None = None,
        new_draft_id: Callable[[], str] | None = None,
        draft_ttl: timedelta = timedelta(minutes=30),
    ) -> None:
        self.repository = repository
        self.generate_deterministic = generate_deterministic
        self.generate_adjusted = generate_adjusted
        self.validate_plan = validate_plan
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.new_id = new_id or (lambda: f"plan-{uuid4().hex}")
        self.new_draft_id = new_draft_id or (lambda: f"draft-{uuid4().hex}")
        self.draft_ttl = draft_ttl

    def draft(self, user_id: str) -> PlanDraft:
        return self._validated_draft(user_id, "deterministic", self.generate_deterministic(user_id))

    def list(self, user_id: str) -> list[StoredPlan]:
        return self.repository.list(user_id)

    def get(self, user_id: str, plan_id: str) -> StoredPlan:
        try:
            plan = self.repository.get(user_id, plan_id)
        except ValueError:
            plan = None
        if plan is None:
            raise ApplicationError(
                code="PLAN_NOT_FOUND",
                message="The requested plan does not exist.",
                status_code=404,
                processing_mode="deterministic",
            )
        return plan

    def adjustment_draft(self, user_id: str, plan_id: str, instructions: str) -> PlanDraft:
        active = self.get(user_id, plan_id)
        payload = self.generate_adjusted(user_id, active, instructions)
        return self._validated_draft(user_id, "agent_adjusted", payload, based_on_plan_id=plan_id)

    def activate(self, user_id: str, draft_id: str) -> StoredPlan:
        draft = self.repository.get_draft(user_id, draft_id)
        if draft is None:
            raise ApplicationError(
                code="PLAN_DRAFT_NOT_FOUND",
                message="The requested plan draft does not exist.",
                status_code=404,
                processing_mode="deterministic",
            )
        if self.now() - draft.created_at > self.draft_ttl:
            raise ApplicationError(
                code="PLAN_DRAFT_EXPIRED",
                message="The plan draft has expired. Generate a new draft before activation.",
                status_code=410,
                processing_mode="deterministic",
            )
        raw = draft.plan.model_dump()
        validation = ValidationResult.model_validate(self.validate_plan(user_id, raw))
        if not validation.passed or validation.violations:
            raise ApplicationError(
                code="PLAN_DRAFT_INVALID",
                message="The plan draft must pass validation before activation.",
                status_code=422,
                processing_mode="deterministic",
            )
        raw["validation"] = validation.model_dump()
        consumed = self.repository.take_draft(user_id, draft_id)
        if consumed is None:
            raise ApplicationError(
                code="PLAN_DRAFT_NOT_FOUND",
                message="The requested plan draft does not exist.",
                status_code=404,
                processing_mode="deterministic",
            )
        stored = StoredPlan(
            plan_id=self.new_id(),
            activated_at=self.now(),
            kind=consumed.kind,
            based_on_plan_id=consumed.based_on_plan_id,
            plan=raw,
        )
        try:
            self.repository.save(user_id, stored)
        except Exception:
            self.repository.save_draft(user_id, consumed)
            raise
        return stored

    def _validated_draft(
        self,
        user_id: str,
        kind: PlanKind,
        payload: dict[str, Any],
        *,
        based_on_plan_id: str | None = None,
    ) -> PlanDraft:
        raw = dict(payload)
        validation = ValidationResult.model_validate(self.validate_plan(user_id, raw))
        raw["validation"] = validation.model_dump()
        draft = PlanDraft(
            draft_id=self.new_draft_id(),
            created_at=self.now(),
            kind=kind,
            based_on_plan_id=based_on_plan_id,
            plan=raw,
        )
        self.repository.save_draft(user_id, draft)
        return draft
