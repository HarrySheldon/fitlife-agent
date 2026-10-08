"""Orchestrating the semantic review as one Runtime-owned model call.

The gate's reviewer is synchronous and the gate runs inside a step, so the model
cannot be called from there. This module performs the call through the Runtime - so
budget, deadline, cancellation and telemetry all apply - and hands the gate a
reviewer that only reports what was already collected.

The distinction that matters most here is between "the review did not happen" and
"the run is over". A provider error means the review is unavailable and stage A's
downgrade applies. A cancellation, a deadline or an exhausted budget means the run
has ended, and reporting that as "unavailable" would turn a cancelled run into a
successful one with a weaker check.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from backend.agent.runtime import BudgetExceeded, RunCancelled, RunTimedOut
from backend.safety.models import SafetyDecision
from backend.safety.review import REVIEW_INSTRUCTIONS, StructuredReviewAdapter

ReviewMode = Literal["off", "shadow", "enforce"]
ReviewStatus = Literal["disabled", "allow", "refuse", "unavailable", "unsupported"]


@dataclass(frozen=True)
class ReviewObservation:
    """What happened, in a form safe to record.

    It holds no question, no draft and no exception text: those are the user's content
    and the provider's internals, and a diagnostic channel is not the place for either.
    """

    mode: ReviewMode
    status: ReviewStatus
    decision: SafetyDecision | None = None


class ReviewUnavailable(RuntimeError):
    """The review could not run. The gate's downgrade path handles this."""


async def collect_review(
    context,
    gateway,
    mode: ReviewMode,
    question: str,
    draft: str,
) -> ReviewObservation:
    """Run the review once, under the Runtime's budget and deadline."""
    if mode == "off":
        return ReviewObservation(mode=mode, status="disabled")

    adapter = StructuredReviewAdapter(gateway=gateway)
    input_text = json.dumps({"question": question, "draft": draft}, ensure_ascii=False)
    # Charged before the call, like every other model input, so a run that cannot
    # afford the review does not make the request.
    context.consume_context(input_text)
    context.consume_context(REVIEW_INSTRUCTIONS)

    try:
        result = await context.tool(
            "safety_review_model", "safe", lambda: adapter.review(question, draft)
        )
    except (BudgetExceeded, RunCancelled, RunTimedOut):
        # The run is over. Propagating keeps the terminal state honest instead of
        # degrading it to "review unavailable".
        raise
    except Exception:
        # A provider failure is a review that did not happen, and stage A decides what
        # that means for the answer.
        return ReviewObservation(mode=mode, status="unavailable")

    context.consume_output(result.output.model_dump_json())
    if result.output.outcome == "refuse":
        return ReviewObservation(
            mode=mode,
            status="refuse",
            decision=SafetyDecision(
                outcome="refuse",
                risk_category=result.output.risk_category,
                violations=(result.output.risk_category,),
            ),
        )
    return ReviewObservation(mode=mode, status="allow")


class ObservationReviewer:
    """Hands the gate what was already collected, and nothing else.

    In shadow mode the answer is unchanged by construction: this reviewer never
    refuses, so the observation is recorded without altering the disposition.
    """

    def __init__(self, observation: ReviewObservation, mode: ReviewMode) -> None:
        self.observation = observation
        self.mode = mode

    def review(self, question: str, draft: str) -> SafetyDecision:
        if self.observation.status == "unavailable":
            # Raise rather than return an allow: the gate's failure path is what keeps
            # the deterministic disposition, and returning allow would be a claim that
            # a review happened and approved.
            raise ReviewUnavailable("The semantic review did not run")
        if self.mode == "enforce" and self.observation.status == "refuse":
            assert self.observation.decision is not None
            return self.observation.decision
        return SafetyDecision(outcome="allow", risk_category="low")
