"""Dictionary matching.

Terms are supplied by a pack; the matcher knows nothing about them. Matching runs
over the normalized text (aspect: every position is a candidate start) and reports
the longest match at each position, so a longer term wins over its own prefix.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

from backend.safety.models import Concern, TermHit
from backend.safety.normalize import Normalized, clause_of, split_clauses


def build_index(concerns: Sequence[Concern]) -> dict[str, tuple[str, int]]:
    """Map a normalized surface term to (concern id, default severity)."""
    index: dict[str, tuple[str, int]] = {}
    for concern in concerns:
        for term in concern.surface:
            folded = term.strip().lower()
            if not folded:
                continue
            index[folded] = (concern.id, concern.default_severity)
    return index


def find_hits(
    normalized: Normalized,
    index: dict[str, tuple[str, int]],
    *,
    concerns: Iterable[Concern] | None = None,
) -> tuple[TermHit, ...]:
    """Longest-match scan over the normalized text."""
    text = normalized.text
    if not text or not index:
        return ()

    clauses = split_clauses(normalized)
    longest = max(len(term) for term in index)
    hits: list[TermHit] = []
    position = 0
    while position < len(text):
        matched = None
        upper = min(len(text), position + longest)
        for end in range(upper, position, -1):
            candidate = text[position:end]
            if candidate in index:
                matched = (candidate, end)
                break
        if matched is None:
            position += 1
            continue
        term, end = matched
        concern_id, severity = index[term]
        span = (position, end)
        hits.append(
            TermHit(
                concern=concern_id,
                span=span,
                clause_index=clause_of(clauses, span),
                default_severity=severity,
            )
        )
        position = end

    return tuple(hits)
