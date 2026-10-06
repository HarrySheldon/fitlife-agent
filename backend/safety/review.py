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

from dataclasses import dataclass
from typing import Protocol

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
