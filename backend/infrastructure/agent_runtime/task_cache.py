"""A bounded in-process cache for deterministic task results.

This module exists to make one claim checkable: **a reused result is still the
result this caller was allowed to see, computed from these exact inputs.** It is
not a general-purpose cache and it is deliberately not persistent -- a miss or a
process restart must never change what the product considers true.

Three rules are structural rather than advisory:

* ``authorize`` runs before the lookup, so a revoked grant cannot be answered
  from memory, and a miss is not a free existence probe.
* ``put`` refuses ``None``. ``None`` means "not computed"; storing it as a
  success is how a temporary failure becomes a permanent answer.
* ``put`` refuses a key with a missing revision (see
  ``DependencyKey.reusable``). Without an authoritative revision there is
  nothing to invalidate against, so such a dependency is recomputed instead.

Nothing here decides *whether* to reuse a result; that is
``backend.domain.task_dependencies``. Nothing here reads a repository, calls a
model or knows what a value contains.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Callable

from backend.domain.task_dependencies import DependencyKey

#: A dependency has no such input (e.g. a meal total has no catalog revision).
#: Distinct from ``""``, which means "we do not know" and therefore forbids reuse.
NOT_APPLICABLE = "-"

#: Shared catalogue rows and pure conversions. Never owner data.
PUBLIC_SCOPE = "public"

_SCOPE_PART = re.compile(r"[A-Za-z0-9_-]{1,48}")


def owner_scope(owner_id: str) -> str:
    """Scope for one owner's private data.

    A caller cannot pass an arbitrary scope string: the identifier is validated,
    so a model-supplied value can never widen the scope it reads from.
    """
    if not isinstance(owner_id, str) or _SCOPE_PART.fullmatch(owner_id) is None:
        raise ValueError("INVALID_OWNER_ID")
    return f"owner:{owner_id}"


def task_scope(owner_id: str, task_id: str) -> str:
    """Scope for one task, bound to its owner.

    A task identifier alone is not unique across owners, so the owner is part of
    the scope: two owners cannot share an entry by choosing the same task id.
    """
    if not isinstance(owner_id, str) or _SCOPE_PART.fullmatch(owner_id) is None:
        raise ValueError("INVALID_OWNER_ID")
    if not isinstance(task_id, str) or _SCOPE_PART.fullmatch(task_id) is None:
        raise ValueError("INVALID_TASK_ID")
    return f"task:{owner_id}.{task_id}"


class TaskResultCache:
    """Bounded, per-scope, version-keyed, copy-on-read.

    ``clock`` is injected and must be monotonic. Expiry is decided by comparing
    a stored deadline with ``clock()``; nothing sleeps and nothing depends on
    wall-clock time, so a test can move time by exactly one second.
    """

    def __init__(self, *, max_entries: int = 128, ttl_seconds: float = 300,
                 clock: Callable[[], float]) -> None:
        if not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError("CACHE_MAX_ENTRIES_MUST_BE_POSITIVE")
        if not isinstance(ttl_seconds, (int, float)) or ttl_seconds <= 0:
            raise ValueError("CACHE_TTL_MUST_BE_POSITIVE")
        if not callable(clock):
            raise ValueError("CACHE_CLOCK_MUST_BE_CALLABLE")
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        # key -> (written_at, expires_at, value). ``written_at`` orders eviction;
        # ``expires_at`` decides validity. They are separate because a rewrite
        # refreshes both while an eviction only cares about age of the write.
        self.entries: dict[DependencyKey, tuple[float, float, Any]] = {}

    # -- reads ---------------------------------------------------------

    def get(self, key: DependencyKey, *, authorize: Callable[[], Any]) -> Any | None:
        """Return an independent copy of the stored value, or ``None``.

        ``authorize`` is called first and its exception propagates: a refusal is
        a refusal even when the bytes happen to be in memory.
        """
        authorize()
        record = self.entries.get(key)
        if record is None:
            return None
        _, expires_at, value = record
        if expires_at <= self.clock():
            self.entries.pop(key, None)
            return None
        return deepcopy(value)

    def __len__(self) -> int:
        """Number of usable entries; expired ones are dropped on the way out."""
        self._drop_expired()
        return len(self.entries)

    def __contains__(self, key: object) -> bool:
        """Existence without authorization -- for inspection and tests only.

        Callers that hand the answer to a user must use :meth:`get`, which
        checks the grant first.
        """
        record = self.entries.get(key)  # type: ignore[arg-type]
        return record is not None and record[1] > self.clock()

    # -- writes --------------------------------------------------------

    def put(self, key: DependencyKey, value: Any) -> None:
        """Store a completed value.

        The copy happens before the entry exists, so a value that cannot be
        copied leaves no half-written entry behind.
        """
        if not isinstance(key, DependencyKey):
            raise ValueError("CACHE_KEY_MUST_BE_A_DEPENDENCY_KEY")
        if value is None:
            raise ValueError("CACHE_MUST_NOT_STORE_A_MISS")
        if not key.reusable:
            raise ValueError("UNVERSIONED_KEY_MUST_NOT_BE_CACHED")
        stored = deepcopy(value)
        now = self.clock()
        self._drop_expired()
        if key not in self.entries and len(self.entries) >= self.max_entries:
            self._evict_oldest_write()
        self.entries[key] = (now, now + self.ttl_seconds, stored)

    def remember(self, key: DependencyKey, producer: Callable[[], Any], *,
                 authorize: Callable[[], Any]) -> Any:
        """Run ``producer`` and store its result only if it finished.

        A cancelled or failed producer raises before ``put`` is reached, so a
        half-finished value can never be published. ``None`` means "nothing
        worth reusing" and is returned without being stored.
        """
        authorize()
        value = producer()
        if value is not None:
            self.put(key, value)
        return value

    def invalidate_scope(self, scope: str) -> int:
        """Drop every entry in one scope; returns how many were removed."""
        doomed = [key for key in self.entries if key.scope == scope]
        for key in doomed:
            self.entries.pop(key, None)
        return len(doomed)

    def invalidate(self, key: DependencyKey) -> bool:
        """Drop one entry; returns whether it was there."""
        return self.entries.pop(key, None) is not None

    def clear(self) -> None:
        self.entries.clear()

    # -- internals -----------------------------------------------------

    def _drop_expired(self) -> None:
        now = self.clock()
        for key in [key for key, record in self.entries.items() if record[1] <= now]:
            self.entries.pop(key, None)

    def _evict_oldest_write(self) -> None:
        oldest = min(self.entries, key=lambda key: self.entries[key][0])
        self.entries.pop(oldest, None)
