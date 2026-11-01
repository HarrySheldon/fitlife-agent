"""Rank fusion, optional reranking and the absence of evidence.

Two properties matter here and both were missing.

**Fusion must be scale-free.** The previous implementation added a vector cosine to a
lexical score. Those are different units, so a keyword hit could outrank a genuinely
relevant chunk simply because its raw number was larger, and rescaling one side would
silently reorder the result. Reciprocal rank fusion only looks at positions, so no
magnitude can buy rank.

**Absence must be expressible.** The previous implementation, when nothing scored above
zero, returned the first ``top_k`` chunks anyway. That turned "the corpus does not
answer this" into "here are three documents", which is the failure the retrieval
contract was written to make unrepresentable.

A reranker orders candidates; it does not certify them. Its scores are deliberately
discarded - the reported score stays the fused one - and every way it can fail
(exception, unknown id, missing result) falls back to the fused order with a named
reason rather than silently producing a different ranking.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.rag.contracts import Hit

RRF_K = 60
DEFAULT_PER_SOURCE_CAP = 2


@dataclass(frozen=True)
class FusedHit:
    chunk_id: str
    content_hash: str
    source: str
    heading: str
    text: str
    score: float


@dataclass(frozen=True)
class RerankOutcome:
    hits: list[FusedHit]
    applied: bool
    reason: str | None


def _fused_hit(hit: Hit, score: float) -> FusedHit:
    return FusedHit(chunk_id=hit.chunk_id, content_hash=hit.content_hash,
                    source=hit.source, heading=hit.heading, text=hit.text, score=score)


def fuse(result_lists: list[list[Hit]], *, k: int = RRF_K) -> list[FusedHit]:
    """Reciprocal rank fusion: ``sum(1 / (k + rank))`` with rank starting at 1.

    Ties break on ``chunk_id`` so the order is reproducible rather than dependent on
    which list happened to be merged first.
    """
    scores: dict[str, float] = {}
    payload: dict[str, Hit] = {}
    for results in result_lists:
        for position, hit in enumerate(results, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + position)
            payload.setdefault(hit.chunk_id, hit)
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [_fused_hit(payload[chunk_id], score) for chunk_id, score in ordered]


def select_with_diversity(hits: list[FusedHit], *, top_k: int,
                          per_source_cap: int = DEFAULT_PER_SOURCE_CAP) -> list[FusedHit]:
    """Take the best ``top_k`` while keeping any one source from filling the list.

    The cap is a ceiling, not a one-per-file rule: if a single document genuinely holds
    the two best chunks, both are allowed through. Excluding the second one is how a
    multi-evidence question lost half its support.
    """
    picked: list[FusedHit] = []
    per_source: dict[str, int] = {}
    for hit in hits:
        if per_source.get(hit.source, 0) >= per_source_cap:
            continue
        picked.append(hit)
        per_source[hit.source] = per_source.get(hit.source, 0) + 1
        if len(picked) >= top_k:
            break
    return picked


def rerank(query: str, hits: list[FusedHit], *, reranker=None) -> RerankOutcome:
    """Optionally reorder fused hits, falling back to the fused order on any problem."""
    if not hits:
        return RerankOutcome(hits=[], applied=False, reason="no_candidates")
    if reranker is None:
        return RerankOutcome(hits=list(hits), applied=False, reason=None)

    try:
        scores = reranker(query, hits)
    except Exception:
        return RerankOutcome(hits=list(hits), applied=False, reason="reranker_error")

    if not isinstance(scores, dict):
        return RerankOutcome(hits=list(hits), applied=False, reason="reranker_invalid")
    if not scores:
        return RerankOutcome(hits=list(hits), applied=False, reason="reranker_missing_result")

    known = {hit.chunk_id for hit in hits}
    if set(scores) - known:
        # An id the reranker invented cannot be placed in the ranking; trusting it
        # would mean inserting a citation nobody retrieved.
        return RerankOutcome(hits=list(hits), applied=False, reason="reranker_unknown_id")
    if set(scores) != known:
        return RerankOutcome(hits=list(hits), applied=False, reason="reranker_missing_result")

    try:
        ordered = sorted(hits, key=lambda hit: (-float(scores[hit.chunk_id]), hit.chunk_id))
    except (TypeError, ValueError):
        return RerankOutcome(hits=list(hits), applied=False, reason="reranker_invalid")

    # The reranker's numbers decide order only; the carried score stays the fused one.
    return RerankOutcome(hits=ordered, applied=True, reason=None)
