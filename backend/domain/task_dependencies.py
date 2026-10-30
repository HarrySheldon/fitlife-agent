"""Versioned dependency identity and the smallest correct invalidation set.

Two claims this module exists to make checkable:

* a change invalidates its dependents and nothing else -- renaming one dish must
  not touch another dish, and must not skip the meal total that reads it;
* a result may only be reused when its whole identity matches: same resource,
  same revision, same constraints, same catalog, same processor. A dependency
  with no authoritative revision is recomputed, because "probably unchanged" is
  how a stale number reaches a published plan.

Nothing here stores a result, reads a repository or knows what a node contains.
The key is an identity; ``infrastructure/agent_runtime/task_cache.py`` is one
consumer and the plan session is another.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping

# ``public`` is a shared catalogue; anything owner- or task-bound names its
# owner, so a model can never choose the scope it reads from. ``task:`` carries
# ``<owner>.<task>`` because a task id alone is not unique across owners; the
# owner segment cannot contain ``.``, so the first dot is the separator.
_SCOPE = re.compile(r"public|(?:owner|task):[A-Za-z0-9_-]{1,48}(?:\.[A-Za-z0-9_-]{1,48})?")
_RESOURCE = re.compile(r"[A-Za-z0-9_.:/-]{1,160}")
_REVISION = re.compile(r"[A-Za-z0-9_.:+/=-]{1,128}")
_NODE = re.compile(r"[A-Za-z0-9_.:/-]{1,120}")

# Why a node was not reused. Closed set: a new reason means a new rule, and a
# report that invents one cannot be compared with the previous run.
REASONS = frozenset({
    "explicitly_changed",
    "version_changed",
    "upstream_changed",
    "revision_unknown",
    "no_previous",
})


@dataclass(frozen=True)
class DependencyKey:
    """Everything a result depends on, so reuse cannot outlive its inputs."""

    scope: str
    resource_id: str
    resource_revision: str
    constraints_revision: str
    catalog_revision: str
    processor_revision: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, str) or _SCOPE.fullmatch(self.scope) is None:
            raise ValueError("UNREGISTERED_DEPENDENCY_SCOPE")
        if not isinstance(self.resource_id, str) or _RESOURCE.fullmatch(self.resource_id) is None:
            raise ValueError("INVALID_RESOURCE_ID")
        for name in ("resource_revision", "constraints_revision", "catalog_revision",
                     "processor_revision"):
            value = getattr(self, name)
            if not isinstance(value, str) or (value and _REVISION.fullmatch(value) is None):
                raise ValueError(f"INVALID_{name.upper()}")

    @property
    def reusable(self) -> bool:
        """A key missing a revision cannot prove it is still valid."""
        return all((self.resource_revision, self.constraints_revision,
                    self.catalog_revision, self.processor_revision))


@dataclass(frozen=True)
class Node:
    """One computed unit and the units it reads."""

    node_id: str
    key: DependencyKey
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or _NODE.fullmatch(self.node_id) is None:
            raise ValueError("INVALID_NODE_ID")
        if not isinstance(self.depends_on, tuple):
            raise ValueError("DEPENDS_ON_MUST_BE_A_TUPLE")
        if any(not isinstance(item, str) or _NODE.fullmatch(item) is None
               for item in self.depends_on):
            raise ValueError("INVALID_DEPENDENCY_ID")
        if self.node_id in self.depends_on:
            raise ValueError("NODE_CANNOT_DEPEND_ON_ITSELF")


def graph_edges(nodes: Iterable[Node]) -> Mapping[str, tuple[str, ...]]:
    """``parent -> children``, the direction invalidation travels."""
    children: dict[str, set[str]] = {}
    for node in nodes:
        for parent in node.depends_on:
            children.setdefault(parent, set()).add(node.node_id)
    return {parent: tuple(sorted(items)) for parent, items in children.items()}


def affected_nodes(changed: Iterable[str], edges: Mapping[str, Iterable[str]]) -> frozenset[str]:
    """Everything reachable from ``changed``.

    A cycle terminates because a node is only queued once. A name that is not in
    the graph is returned as itself: an unknown node widens nothing.
    """
    affected = set(changed)
    pending = list(affected)
    while pending:
        for child in edges.get(pending.pop(), ()):
            if child not in affected:
                affected.add(child)
                pending.append(child)
    return frozenset(affected)


@dataclass(frozen=True)
class RecomputeOutcome:
    """What may be reused, what must be dropped, and why."""

    reused: tuple[str, ...] = ()
    invalidated: tuple[str, ...] = ()
    computed: tuple[str, ...] = ()
    reasons: Mapping[str, str] = field(default_factory=dict)

    def as_record(self) -> dict:
        """Counts and reason codes. Node identifiers stay out of the record."""
        histogram: dict[str, int] = {}
        for reason in self.reasons.values():
            histogram[reason] = histogram.get(reason, 0) + 1
        return {"reused": len(self.reused), "invalidated": len(self.invalidated),
                "computed": len(self.computed),
                "reasons": dict(sorted(histogram.items()))}


def plan_recompute(nodes: Iterable[Node], previous: Mapping[str, DependencyKey], *,
                   changed: Iterable[str] = (),
                   versions_changed: Iterable[str] = ()) -> RecomputeOutcome:
    """Decide reuse per node, in the order the nodes were given.

    ``changed`` are nodes whose *inputs* changed; ``versions_changed`` are nodes
    whose own identity moved. A node whose key no longer matches the key its
    previous result was computed with is invalidated even when nobody named it --
    that is the whole point of carrying the key.
    """
    nodes = tuple(nodes)
    explicit = frozenset(changed)
    moved = frozenset(versions_changed)
    edges = graph_edges(nodes)

    # A node whose own key moved is a change for its dependents too, so the
    # closure has to be taken over both sources before anything is classified.
    drifted = {node.node_id for node in nodes
               if node.node_id in previous and previous[node.node_id] != node.key}
    uncertain = {node.node_id for node in nodes
                 if not node.key.reusable or node.node_id not in previous}
    affected = affected_nodes(explicit | moved | drifted | uncertain, edges)

    reused: list[str] = []
    invalidated: list[str] = []
    computed: list[str] = []
    reasons: dict[str, str] = {}
    for node in nodes:
        if node.node_id in explicit:
            reasons[node.node_id] = "explicitly_changed"
        elif not node.key.reusable:
            # No authoritative revision: recompute rather than guess. This is
            # reported ahead of "version moved" because the missing revision is
            # the operative fact -- there is nothing to compare against.
            reasons[node.node_id] = "revision_unknown"
        elif node.node_id in moved or node.node_id in drifted:
            reasons[node.node_id] = "version_changed"
        elif node.node_id not in previous:
            reasons[node.node_id] = "no_previous"
        elif node.node_id in affected:
            reasons[node.node_id] = "upstream_changed"
        else:
            reused.append(node.node_id)
            continue
        (invalidated if node.node_id in previous else computed).append(node.node_id)
    return RecomputeOutcome(reused=tuple(reused), invalidated=tuple(invalidated),
                            computed=tuple(computed), reasons=reasons)


def domain_reuse(frozen: Mapping[str, str], actual: Mapping[str, str],
                 touched: Iterable[str]) -> RecomputeOutcome:
    """The plan task's view: per-domain carry-over, expressed in the same terms.

    ``frozen`` is what a domain hashed to when it last passed; ``actual`` is what
    it hashes to now. A domain that is touched is recomputed by definition; a
    domain that is untouched but whose bytes moved is invalidated, not reused.
    """
    touched = frozenset(touched)
    reused: list[str] = []
    invalidated: list[str] = []
    computed: list[str] = []
    reasons: dict[str, str] = {}
    for domain in sorted(set(frozen) | set(actual) | touched):
        if domain in touched:
            reasons[domain] = "explicitly_changed"
        elif domain in frozen and domain in actual and frozen[domain] == actual[domain]:
            reused.append(domain)
            continue
        elif domain in frozen:
            reasons[domain] = "version_changed"
        else:
            reasons[domain] = "no_previous"
        (invalidated if domain in frozen else computed).append(domain)
    return RecomputeOutcome(reused=tuple(reused), invalidated=tuple(invalidated),
                            computed=tuple(computed), reasons=reasons)
