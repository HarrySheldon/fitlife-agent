"""Deterministic execution strategy selection.

The facts here are produced by the application and its validators. A model may
describe a request as "simple"; that sentence is not an input to this module.
The only accepted action name is a registered identifier, so a user cannot type
a shortcut into existence.

Stage A is intentionally inert: ``REGISTERED_TRUSTED_ACTIONS`` is empty, so an
optimized plan is byte-for-byte the reference plan. Registering an action is a
deliberate act that belongs to the optimisation step, together with the
measurement that justifies it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

ExecutionStrategy = Literal["reference", "optimized"]
STRATEGIES = frozenset({"reference", "optimized"})
TASK_KINDS = frozenset({"coach_chat", "entry", "plan_adjustment"})

# Closed table of trusted actions that may skip a discovery round. Empty until a
# shortcut is implemented and measured; see S4-B1.
REGISTERED_TRUSTED_ACTIONS: frozenset[str] = frozenset()

_ACTION = re.compile(r"[a-z][a-z0-9_]{0,63}")


@dataclass(frozen=True)
class TaskFacts:
    """What the application knows before choosing an execution path."""

    task_kind: str
    trusted_action: str | None = None
    fields_complete: bool = False
    catalog_unambiguous: bool = False
    scope_verified: bool = False
    constraints_complete: bool = False

    def __post_init__(self) -> None:
        if self.task_kind not in TASK_KINDS:
            raise ValueError("Unregistered task kind")
        if self.trusted_action is not None:
            if not isinstance(self.trusted_action, str) or _ACTION.fullmatch(self.trusted_action) is None:
                raise ValueError("trusted_action must be a registered identifier")
        for name in ("fields_complete", "catalog_unambiguous", "scope_verified", "constraints_complete"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean fact")

    @property
    def deterministic(self) -> bool:
        """True only when nothing about this task needs a model decision."""
        return self.scope_verified and self.fields_complete and self.constraints_complete


@dataclass(frozen=True)
class ExecutionPlan:
    strategy: str
    use_shortcut: bool = False
    reasons: tuple[str, ...] = ()


def plan_execution(strategy: str, facts: TaskFacts) -> ExecutionPlan:
    """Choose a path and say why, so an unexplained shortcut cannot appear."""
    if strategy not in STRATEGIES:
        raise ValueError("Unregistered execution strategy")
    if strategy == "reference":
        return ExecutionPlan(strategy=strategy, use_shortcut=False, reasons=("reference_strategy",))
    if not facts.scope_verified:
        return ExecutionPlan(strategy=strategy, reasons=("scope_not_verified",))
    if facts.trusted_action is None:
        return ExecutionPlan(strategy=strategy, reasons=("no_trusted_action",))
    if not (facts.fields_complete and facts.constraints_complete):
        return ExecutionPlan(strategy=strategy, reasons=("facts_incomplete",))
    if facts.trusted_action not in REGISTERED_TRUSTED_ACTIONS:
        return ExecutionPlan(strategy=strategy, reasons=("action_not_registered",))
    return ExecutionPlan(strategy=strategy, use_shortcut=True, reasons=("shortcut_selected",))
