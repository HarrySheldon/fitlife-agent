"""Which context a run may prefetch, and how the rear of a long prompt is trimmed.

Two properties keep this module from becoming an authorization back door:

* the prefetch table is closed and keyed by a *registered* action, so a user who
  types an action identifier into the question box selects nothing -- the fact
  comes from the page the application generated, not from the text;
* a prefetched resource is read through ``SkillCatalog.read``, which verifies the
  release digest, so a trusted identifier never means trusted bytes.

Nothing here grants a domain. A prefetch is a ``resources.read`` of a published
skill; private records still require a tool call the executor authorizes, which
is why this module is a pure strategy and holds no executor.

Stage B is deliberately narrow. One action has a measured discovery round to
save; registering another is an act that comes with its own measurement, not a
side effect of this module existing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

from backend.agent.tasks.execution_policy import STRATEGIES, TaskFacts
from backend.domain.coach_answer import ACTION_REGISTRY, ADVICE_REGISTRY

# The identifier recorded in the treatment fingerprint. It names the policy this
# module implements, so a report can never attribute a saving to a policy that
# was not the one running.
CONTEXT_POLICY_VERSION = "context-policy-v1"

REGISTERED_ACTIONS: frozenset[str] = frozenset(ACTION_REGISTRY) | frozenset(ADVICE_REGISTRY)

# A verified page projection is private record data, so it may only be attached
# when an application-side producer exists that computes it deterministically and
# hands it through a sanitisation step. There is none yet, and an empty set here
# is what makes ``include_verified_page_context`` unable to be switched on by
# accident.
VERIFIED_PAGE_CONTEXT_KEYS: frozenset[str] = frozenset()

_MAX_RESOURCE_ID = 160


@dataclass(frozen=True)
class PrefetchEntry:
    resource_ids: tuple[str, ...] = ()
    include_verified_page_context: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.resource_ids, tuple):
            raise ValueError("PREFETCH_RESOURCES_MUST_BE_A_TUPLE")
        for resource_id in self.resource_ids:
            if (not isinstance(resource_id, str) or not resource_id.startswith("skill:")
                    or len(resource_id) > _MAX_RESOURCE_ID):
                raise ValueError("PREFETCH_RESOURCE_MUST_BE_A_PUBLISHED_SKILL")
        if type(self.include_verified_page_context) is not bool:
            raise ValueError("PREFETCH_FLAG_MUST_BE_A_BOOLEAN")
        if self.include_verified_page_context and not VERIFIED_PAGE_CONTEXT_KEYS:
            raise ValueError("NO_VERIFIED_PAGE_CONTEXT_PRODUCER")


# Closed table. ``explain_today`` is the only action whose shortcut has been
# measured: without it the run spends two decisions discovering the single skill
# that answers it. Every other action keeps discovering progressively.
PREFETCH_TABLE: Mapping[str, PrefetchEntry] = {
    "explain_today": PrefetchEntry(resource_ids=("skill:today-explanation",)),
}


@dataclass(frozen=True)
class ContextPlan:
    resource_ids: tuple[str, ...] = ()
    include_verified_page_context: bool = False


def choose_context_plan(strategy: str, facts: TaskFacts, *, prefetch_enabled: bool = True) -> ContextPlan:
    """The extra context this run may assemble before its first decision."""
    if strategy not in STRATEGIES:
        raise ValueError("Unregistered execution strategy")
    if type(prefetch_enabled) is not bool:
        raise ValueError("prefetch_enabled must be a boolean fact")
    # The reference side is the baseline; it must not contain the thing being
    # measured, so prefetching is off there regardless of the deployment switch.
    if strategy != "optimized" or not prefetch_enabled:
        return ContextPlan()
    if facts.scope_verified is not True or facts.trusted_action is None:
        return ContextPlan()
    entry = PREFETCH_TABLE.get(facts.trusted_action)
    if entry is None:
        return ContextPlan()
    return ContextPlan(resource_ids=entry.resource_ids,
                       include_verified_page_context=entry.include_verified_page_context)


def scope_verified(command) -> bool:
    """A trusted page intent is one the application generated for a page action.

    A page action carrying the user's own text is not one: the text may name a
    different task than the page did.
    """
    if command.trusted_page_intent is not True:
        return False
    return not (command.raw_coach_question or "").strip()


def trusted_action_of(command) -> str | None:
    """The verified registered action name, or None.

    A free string is never an action, however it is spelled or wherever it was
    typed, and a page action carrying the user's own text is not one either: the
    text may name a different task than the page did. ``TaskFacts`` refuses a
    non-identifier, so this check has to happen before the facts are built
    rather than inside them.
    """
    action = command.coach_action
    if not isinstance(action, str) or action not in REGISTERED_ACTIONS:
        return None
    return action if scope_verified(command) else None


def task_facts_for(command) -> TaskFacts:
    return TaskFacts(task_kind="coach_chat", trusted_action=trusted_action_of(command),
                     scope_verified=scope_verified(command))


@dataclass(frozen=True)
class ContextPolicyConfig:
    strategy: str = "reference"
    prefetch_enabled: bool = True
    version: str = CONTEXT_POLICY_VERSION
    max_chars: int = 24000

    def __post_init__(self) -> None:
        if self.strategy not in STRATEGIES:
            raise ValueError("Unregistered execution strategy")
        if type(self.prefetch_enabled) is not bool:
            raise ValueError("prefetch_enabled must be a boolean")
        if self.version != CONTEXT_POLICY_VERSION:
            # A recorded version that does not name the running code would let a
            # report attribute a saving to a policy that was never executed.
            raise ValueError("CONTEXT_POLICY_VERSION_MISMATCH")
        if type(self.max_chars) is not int or not 1000 <= self.max_chars <= 200_000:
            raise ValueError("CONTEXT_CHARS_INVALID")

    @property
    def organizes(self) -> bool:
        """Only the optimized side compacts; the baseline keeps every byte."""
        return self.strategy == "optimized"

    def plan_for(self, command) -> ContextPlan:
        return choose_context_plan(self.strategy, task_facts_for(command),
                                   prefetch_enabled=self.prefetch_enabled)


_COMPACTABLE_SOURCE = "tool_data"


def _chars(messages) -> int:
    return len(json.dumps(list(messages), ensure_ascii=False, sort_keys=True, default=str))


def _stub(item) -> dict:
    """Identity without payload: what a later decision may still depend on."""
    return {"role": item.get("role", "user"), "source": item["source"],
            "revision": item.get("revision"), "call_id": item.get("call_id"),
            "tool": item.get("tool"), "status": item.get("status", "ok"),
            "source_version": item.get("source_version"),
            "required_domains": list(item.get("required_domains") or []),
            "compacted": True,
            "content": json.dumps({"compacted": True, "call_id": item.get("call_id")},
                                  ensure_ascii=False, sort_keys=True)}


def organize_rear(messages, *, max_chars: int, keep_recent: int = 2):
    """Compact the bodies of older completed observations, keeping their provenance.

    Only ``tool_data`` is eligible, only the oldest entries are taken, and the
    most recent ``keep_recent`` are left alone because the current decision is
    still using them. A refusal is never compacted: it carries a hard limit, and
    a limit the model cannot see is one it will try to cross again. The current
    request and the runtime frame are not observations and are never touched.
    """
    if type(keep_recent) is not int or keep_recent < 0:
        raise ValueError("keep_recent must be a non-negative integer")
    items = tuple(messages)
    if _chars(items) <= max_chars:
        return items
    candidates = [index for index, item in enumerate(items)
                  if item.get("source") == _COMPACTABLE_SOURCE and item.get("status", "ok") == "ok"
                  and not _protected_observation(item)]
    protected = set(candidates[len(candidates) - keep_recent:]) if keep_recent else set()
    result = list(items)
    for index in candidates:
        if index in protected:
            continue
        result[index] = _stub(items[index])
        if _chars(result) <= max_chars:
            break
    return tuple(result)


def _protected_observation(item) -> bool:
    # Private facts and published instructions can constrain every later action.
    # Only discovery metadata is disposable without a domain-aware summarizer.
    return item.get('tool') not in {'skills.search'}
