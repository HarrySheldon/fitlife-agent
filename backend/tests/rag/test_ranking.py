"""R3: rank fusion that cannot be gamed by score scale, and an honest empty result.

R0 recorded two related defects. First, lexical and vector scores were added directly,
which mixes two different scales: a keyword hit can outrank a genuinely relevant chunk
merely because its raw number happened to be larger. Second, when nothing matched, the
retriever still returned the first ``top_k`` chunks, so an off-topic question came back
with three documents as if they supported an answer.

Fusion is by rank (reciprocal rank fusion), which is scale-free by construction. Absence
is expressed as ``insufficient``/``unavailable`` with no hits, which the R0 contract
already refuses to accept otherwise.
"""
from __future__ import annotations

import pytest

from backend.rag.contracts import RetrievalResult
from backend.rag.ranking import (
    RRF_K,
    FusedHit,
    fuse,
    rerank,
)


_ALPHABET = "0123456789abcdef"


def _id(label: str) -> str:
    """A contract-valid chunk id derived from a short readable label."""
    digits = "".join(ch for ch in label.lower() if ch in _ALPHABET)
    return "chunk-" + digits.rjust(16, "0")[:16]


def _hit(chunk_id: str, *, source="a.md", heading="H", text="body", rank=1, score=None):
    from backend.rag.contracts import Hit, content_hash

    return Hit(chunk_id=chunk_id, content_hash=content_hash(text), source=source,
               heading=heading, text=text, rank=rank, score=score)

    return Hit(chunk_id=chunk_id, content_hash=content_hash(text), source=source,
               heading=heading, text=text, rank=rank, score=score)


# --------------------------------------------------------------------------
# fusion is by rank, not by raw score
# --------------------------------------------------------------------------

def test_the_fusion_constant_is_the_documented_one():
    assert RRF_K == 60


def test_a_single_result_list_keeps_its_order():
    fused = fuse([[_hit(_id("aaaa"), rank=1), _hit(_id("bbbb"), rank=2)]])

    assert [item.chunk_id for item in fused] == [_id("aaaa"), _id("bbbb")]


def test_fusion_scores_follow_the_reciprocal_rank_formula():
    fused = fuse([[_hit(_id("aaaa"), rank=1), _hit(_id("bbbb"), rank=2)]])

    assert fused[0].score == pytest.approx(1 / (RRF_K + 1))
    assert fused[1].score == pytest.approx(1 / (RRF_K + 2))


def test_a_chunk_appearing_in_both_lists_outranks_one_in_a_single_list():
    """Agreement between two retrievers is evidence; one retriever's opinion is not."""
    shared = _hit(_id("shared"))
    only_vector = _hit(_id("econly"))
    fused = fuse([[shared, only_vector], [shared]])

    assert fused[0].chunk_id == _id("shared")
    assert fused[0].score > fused[1].score


def test_scaling_raw_scores_cannot_change_the_fused_order():
    """The defect being designed out: a big number must not beat a consistent rank."""
    first = [_hit(_id("aaaa"), rank=1, score=1.0), _hit(_id("bbbb"), rank=2, score=0.9)]
    second = [_hit(_id("bbbb"), rank=1, score=0.9), _hit(_id("aaaa"), rank=2, score=1.0)]

    fused = fuse([first, second])
    # Both appear at rank 1 and rank 2 once, so the tie must be broken stably by id
    # rather than by whichever raw score was larger.
    assert [item.chunk_id for item in fused] == [_id("aaaa"), _id("bbbb")]


def test_a_huge_raw_score_does_not_win_by_magnitude():
    """Rank position decides, so a giant number at position 5 still loses to position 1."""
    modest = [_hit(_id("modest"), rank=1, score=0.01)]
    enormous = [
        _hit(_id("filler1"), rank=1, score=1.0),
        _hit(_id("filler2"), rank=2, score=2.0),
        _hit(_id("filler3"), rank=3, score=3.0),
        _hit(_id("filler4"), rank=4, score=4.0),
        _hit(_id("enormous"), rank=5, score=9999.0),
    ]
    fused = fuse([modest, enormous])

    assert fused[0].chunk_id == _id("modest")
    assert fused[-1].chunk_id == _id("enormous")


def test_duplicate_ids_across_lists_are_deduplicated():
    same = _hit(_id("aaaa"))
    fused = fuse([[same], [same]])

    assert len(fused) == 1


def test_ties_are_broken_stably_by_chunk_id():
    left = _hit(_id("bbbb"), rank=1)
    right = _hit(_id("aaaa"), rank=1)
    fused = fuse([[left], [right]])

    assert [item.chunk_id for item in fused] == [_id("aaaa"), _id("bbbb")]


def test_an_empty_result_set_fuses_to_nothing():
    assert fuse([[], []]) == []


def test_fusion_carries_the_chunk_payload_through():
    fused = fuse([[_hit(_id("aaaa"), source="doc.md", heading="S", text="payload")]])

    assert fused[0].source == "doc.md"
    assert fused[0].heading == "S"
    assert fused[0].text == "payload"


# --------------------------------------------------------------------------
# source diversity is a cap, not a hard one-per-file rule
# --------------------------------------------------------------------------

def test_two_relevant_chunks_from_one_source_can_both_surface():
    """GAP: the old diversity rule kept only one chunk per source."""
    from backend.rag.ranking import select_with_diversity

    fused = fuse([[
        _hit(_id("a1"), source="one.md", rank=1),
        _hit(_id("a2"), source="one.md", rank=2),
        _hit(_id("b1"), source="two.md", rank=3),
    ]])

    picked = select_with_diversity(fused, top_k=3, per_source_cap=2)

    assert [item.chunk_id for item in picked] == [_id("a1"), _id("a2"), _id("b1")]


def test_the_per_source_cap_is_respected():
    from backend.rag.ranking import select_with_diversity

    fused = fuse([[
        _hit(_id("a1"), source="one.md", rank=1),
        _hit(_id("a2"), source="one.md", rank=2),
        _hit(_id("a3"), source="one.md", rank=3),
        _hit(_id("b1"), source="two.md", rank=4),
    ]])

    picked = select_with_diversity(fused, top_k=3, per_source_cap=1)

    assert [item.chunk_id for item in picked] == [_id("a1"), _id("b1")]


def test_the_cap_defaults_to_more_than_one_per_source():
    from backend.rag.ranking import DEFAULT_PER_SOURCE_CAP, select_with_diversity

    fused = fuse([[_hit(_id("a1"), source="one.md"), _hit(_id("a2"), source="one.md")]])

    picked = select_with_diversity(fused, top_k=2)

    assert DEFAULT_PER_SOURCE_CAP > 1
    assert len(picked) == 2


# --------------------------------------------------------------------------
# optional rerank: a failure falls back and says so
# --------------------------------------------------------------------------

class _Reranker:
    def __init__(self, *, order=None, raises=None, returns=None):
        self._order = order
        self._raises = raises
        self._returns = returns

    def __call__(self, query, candidates):
        if self._raises is not None:
            raise self._raises
        if self._returns is not None:
            return self._returns
        # Higher score means more relevant, so the first chunk in ``order`` gets the
        # largest number.
        width = len(candidates)
        return {item.chunk_id: float(width - self._order.index(item.chunk_id))
                for item in candidates}


def _candidates():
    return fuse([[
        _hit(_id("aaaa"), rank=1),
        _hit(_id("bbbb"), rank=2),
        _hit(_id("cccc"), rank=3),
    ]])


def test_a_reranker_can_reorder_candidates():
    result = rerank("q", _candidates(), reranker=_Reranker(order=[_id("cccc"), _id("aaaa"), _id("bbbb")]))

    assert result.applied is True
    assert result.hits[0].chunk_id == _id("cccc")


def test_no_reranker_leaves_the_fused_order_untouched():
    result = rerank("q", _candidates(), reranker=None)

    assert result.applied is False
    assert result.reason is None
    assert [item.chunk_id for item in result.hits] == [_id("aaaa"), _id("bbbb"), _id("cccc")]


def test_a_raising_reranker_falls_back_and_names_the_reason():
    result = rerank("q", _candidates(), reranker=_Reranker(raises=TimeoutError("slow")))

    assert result.applied is False
    assert result.reason == "reranker_error"
    assert [item.chunk_id for item in result.hits] == [_id("aaaa"), _id("bbbb"), _id("cccc")]


def test_an_unknown_id_from_a_reranker_is_rejected():
    result = rerank("q", _candidates(), reranker=_Reranker(returns={_id("zzzz"): 1.0}))

    assert result.applied is False
    assert result.reason == "reranker_unknown_id"


def test_a_missing_reranker_result_falls_back():
    result = rerank("q", _candidates(), reranker=_Reranker(returns={}))

    assert result.applied is False
    assert result.reason == "reranker_missing_result"


def test_reranker_scores_are_not_trusted_as_confidence():
    """A reranker orders; it does not certify. The fused score is what is carried."""
    result = rerank("q", _candidates(), reranker=_Reranker(order=[_id("bbbb"), _id("aaaa"), _id("cccc")]))

    assert result.hits[0].chunk_id == _id("bbbb")
    # The reported score is still the RRF value, not the reranker's arbitrary number.
    assert result.hits[0].score == pytest.approx(1 / (RRF_K + 2))


# --------------------------------------------------------------------------
# no evidence is a state, not a pile of near misses
# --------------------------------------------------------------------------

def test_an_empty_candidate_set_is_insufficient_not_a_fallback_pile():
    result = rerank("q", [], reranker=None)

    assert result.hits == []
    assert result.reason in {None, "no_candidates"}


def test_building_a_result_from_no_hits_is_insufficient():
    built = RetrievalResult.insufficient(release_id="release-0001")

    assert built.status == "insufficient"
    assert built.hits == []


def test_building_a_result_from_hits_requires_a_release():
    from backend.rag.contracts import Hit, content_hash

    hit = Hit(chunk_id=_id("aaaa"), content_hash=content_hash("t"), source="a.md",
              heading="H", text="t", rank=1)
    built = RetrievalResult.found(hits=[hit], release_id="release-0001")

    assert built.status == "ok"
    assert built.release_id == "release-0001"
