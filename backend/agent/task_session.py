"""The seam between the decision loop and whatever task is driving it.

The loop asks the session three questions and never the other way round:

* ``before_decision`` -- may this continue, and what is the trusted state right
  now? Called at the top of every round and again immediately before the
  gateway callback, so a permission revoked while the run waited in the worker
  queue is caught before already-read private data reaches a provider.
* ``after_decision`` -- observe a decision that already passed validation. This
  is a notification, never a source of authority: a session cannot promote model
  text into a permission.
* ``before_delivery`` -- the receipt shown to the user. Built by trusted code, so
  the model cannot construct or edit it.

Rounds advance only through the persistent compare-and-swap in the task
repository. Repeating ``before_decision`` is therefore side-effect free.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from backend.agent.decision import AgentDecision


@dataclass(frozen=True)
class SessionFrame:
    """What the loop may rely on for this round. Built from trusted state."""

    revision: int
    phase: str
    state: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("SESSION_REVISION_INVALID")
        if not isinstance(self.phase, str) or not self.phase.strip():
            raise ValueError("SESSION_PHASE_REQUIRED")
        if not isinstance(self.state, Mapping):
            raise ValueError("SESSION_STATE_INVALID")


class TaskSession(Protocol):
    def before_decision(self) -> SessionFrame: ...

    def after_decision(self, decision: AgentDecision) -> None: ...

    def before_delivery(self, decision: AgentDecision) -> Mapping[str, Any]: ...


class AdviceSession:
    """No task, no rounds, no side effects.

    Plain advice keeps exactly the behaviour it had before task sessions existed:
    an empty frame, no observation, an empty receipt.
    """

    def before_decision(self) -> SessionFrame:
        return SessionFrame(revision=0, phase="advice", state={})

    def after_decision(self, decision: AgentDecision) -> None:
        return None

    def before_delivery(self, decision: AgentDecision) -> Mapping[str, Any]:
        return {}
