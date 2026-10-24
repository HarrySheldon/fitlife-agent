"""The two tools a bound plan task may use, and nothing else.

Neither tool takes an owner, a task id, a round, a version or a confirmation
flag. Those come from the session the application bound to the run, so a model
cannot point a candidate at somebody else's task or claim a round it did not
reserve.

``plan.submit_candidate`` is a draft write: it is never replayed and never
cached. Business idempotency is the round scope inside the session, not a
transport retry.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backend.agent.tools.spec import ToolAccess, ToolSpec
from backend.domain.plan_adjustment import MAX_PATCHES, Patch


class ReadBaseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: list[str] = Field(min_length=1, max_length=4)


class SubmitCandidateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patches: list[Patch] = Field(min_length=1, max_length=MAX_PATCHES)


def _require_session(access: ToolAccess) -> None:
    from backend.agent.plan_adjustment.session import PlanTaskSession
    if not isinstance(access.session, PlanTaskSession):
        # Without a bound task there is no base plan and no candidate to own.
        raise PermissionError("TASK_SESSION_REQUIRED")


PLAN_TOOL_SPECS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            name="plan.read_base",
            args_model=ReadBaseArgs,
            effect="private_read",
            authorize=_require_session,
            handler=lambda args, ctx: ctx.session.read_base(args.fields),
        ),
        ToolSpec(
            name="plan.submit_candidate",
            args_model=SubmitCandidateArgs,
            effect="draft_write",
            read_only=False,
            replay="never",
            authorize=_require_session,
            handler=lambda args, ctx: ctx.session.submit_candidate(args.patches),
        ),
    )
}
