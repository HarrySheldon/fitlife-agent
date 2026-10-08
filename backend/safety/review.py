"""A model-backed reviewer for what a word list cannot express.

The deterministic rules match known vocabulary. That is the right tool for "do not
tell someone to stop their medication", where the terms are enumerable and the check
must be reproducible. It is the wrong tool for judging whether an answer is
demeaning, because the clearest cases are the ones no list contains: ToxiCN's own
paper notes that a term like 小仙女 is a compliment used as an insult, and an insult
lexicon cannot hold it. Deciding that requires reading the sentence.

So this reviewer is deliberately *not* a vocabulary check. It asks a model one
narrow question about the draft, and it is placed where the gate already guarantees
it can only make things stricter: it runs after the deterministic decision, it can
only turn an allow into a refusal, and it cannot relax anything.

Two consequences are accepted rather than hidden:

- it costs one extra model call per answer it is enabled for;
- it is non-deterministic, so its own behaviour cannot be pinned by a unit test the
  way the rule engine can. What is tested here is the contract around it - what it
  may return, what happens when it fails, and that it cannot loosen a decision.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, model_validator

from backend.safety.models import SafetyDecision

# The question is narrow on purpose. A reviewer asked to judge "safety" in general
# duplicates the deterministic gate and starts refusing ordinary answers; asked
# about one failure mode, it stays comparable to what a person would say.
REVIEW_INSTRUCTIONS = """You are reviewing one draft answer from a fitness and nutrition assistant.

Answer exactly one question: does the draft demean, insult, mock or shame the user,
or attack them personally (including their body, their progress, or a group they
belong to)?

Judge only that. Do not judge medical accuracy, tone, length, or helpfulness; other
checks cover those, and flagging them here would suppress answers that are fine.

Calling someone names, telling them they are worthless or hopeless, and insulting
their body or their rate of progress all count. Encouraging, neutral and plainly
factual statements do not, even when the facts are unwelcome - telling someone their
intake exceeded their target is reporting, not insulting.

Return a verdict with:
- outcome: "refuse" when the draft demeans the user, otherwise "allow"
- risk_category: "harassment" when refusing, otherwise "low"
"""


class ReviewModel(Protocol):
    """The one capability this reviewer needs from a model gateway."""

    def judge_review(self, instructions: str, question: str, draft: str) -> SafetyDecision: ...


@dataclass
class ModelSafetyReviewer:
    """Adapts a model gateway to the reviewer the gate expects.

    The gate calls ``review(question, draft)``; everything about prompts and
    structured output stays on this side of the boundary, so the engine keeps
    knowing nothing about how a judgement is produced.
    """

    model: ReviewModel
    instructions: str = REVIEW_INSTRUCTIONS

    def review(self, question: str, draft: str) -> SafetyDecision:
        decision = self.model.judge_review(self.instructions, question, draft)
        if not isinstance(decision, SafetyDecision):
            raise ValueError("The review model must return a SafetyDecision")
        return decision


class ReviewVerdict(BaseModel):
    """What the review model is allowed to say.

    Two legal pairings and nothing else. The model is not handed ``SafetyDecision``
    to fill in: that type carries `rewrite`, disclaimers and free-form reason strings
    which the reviewer has no business setting, and a model asked to fill them would
    eventually use one.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    outcome: Literal["allow", "refuse"]
    risk_category: Literal["low", "harassment"]

    @model_validator(mode="after")
    def check_pair(self):
        if (self.outcome, self.risk_category) not in {("allow", "low"), ("refuse", "harassment")}:
            raise ValueError("Invalid review verdict pair")
        return self


@dataclass
class StructuredReviewAdapter:
    """Asks a structured gateway the review question.

    The draft is passed as data rather than interpolated into the instructions, so a
    draft cannot rewrite the question it is being judged against.
    """

    gateway: object  # StructuredModelGateway; kept loose to avoid a layer import
    instructions: str = REVIEW_INSTRUCTIONS

    def review(self, question: str, draft: str):
        input_text = json.dumps(
            {"question": question, "draft": draft}, ensure_ascii=False
        )
        return self.gateway.parse_structured(
            instructions=self.instructions,
            input_text=input_text,
            response_model=ReviewVerdict,
        )
