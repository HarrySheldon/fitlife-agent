"""R0: fix the contracts and record the current gaps as red evidence.

R0 does not fix retrieval. It pins three things:

1. the shapes a governed retrieval must eventually produce (chunk identity, manifest,
   explicit status);
2. a fixed synthetic corpus with labelled, dev/holdout-separated queries;
3. the two known defects, reproduced and kept as ``xfail`` markers so R1/R2 have
   something concrete to turn green.

The defects are marked ``strict=True``: when a later stage fixes them the marker itself
fails, which is the signal to delete it. A silently-passing xfail would let the fix go
unnoticed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.rag.contracts import (
    CHUNKING_VERSION,
    Chunk,
    Hit,
    IndexManifest,
    QueryCase,
    RetrievalCorpus,
    RetrievalResult,
    chunk_id,
    content_hash,
    corpus_digest,
    document_version,
    locator,
    normalise_text,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rag"


def _corpus_payload() -> dict:
    return json.loads((FIXTURES / "corpus.json").read_text(encoding="utf-8"))


def _corpus() -> RetrievalCorpus:
    return RetrievalCorpus.model_validate(_corpus_payload())


# --------------------------------------------------------------------------
# chunk identity
# --------------------------------------------------------------------------

def test_chunk_identity_is_position_based_and_content_checked():
    text = "Increase weekly volume gradually."
    chunk = Chunk(
        chunk_id=chunk_id("training-load.md", "Progressive overload", 0),
        content_hash=content_hash(text),
        document_version=document_version("whole document"),
        source="training-load.md",
        heading="Progressive overload",
        text=text,
        ordinal=0,
    )

    assert chunk.chunk_id.startswith("chunk-")
    assert chunk.content_hash == content_hash(text)


def test_a_chunk_whose_hash_does_not_match_its_text_is_rejected():
    """A stale hash would make an edited chunk look unchanged."""
    with pytest.raises(ValidationError, match="content_hash"):
        Chunk(
            chunk_id=chunk_id("a.md", "H", 0),
            content_hash=content_hash("different text"),
            document_version=document_version("doc"),
            source="a.md",
            heading="H",
            text="actual text",
            ordinal=0,
        )


def test_the_same_position_keeps_its_id_when_the_text_changes():
    """The id identifies the position; the hash identifies the version at it."""
    first = chunk_id("editable.md", "Version marker", 0)
    second = chunk_id("editable.md", "Version marker", 0)
    other_position = chunk_id("editable.md", "Second block", 0)

    assert first == second
    assert first != other_position


def test_two_documents_sharing_a_heading_do_not_collide():
    assert chunk_id("a.md", "Notes", 0) != chunk_id("b.md", "Notes", 0)


def test_ordinal_separates_two_chunks_under_one_heading():
    assert chunk_id("a.md", "Notes", 0) != chunk_id("a.md", "Notes", 1)


def test_content_change_changes_the_hash():
    assert content_hash("alpha") != content_hash("beta")


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------

def _manifest(**overrides) -> IndexManifest:
    values = {
        "schema_version": 1,
        "release_id": "release-0001",
        "corpus_digest": "a" * 64,
        "chunking_version": CHUNKING_VERSION,
        "embedding_provider": "hashing",
        "embedding_model": "hashing-512",
        "embedding_dimensions": 512,
        "config_digest": "b" * 64,
        "chunk_count": 7,
    }
    values.update(overrides)
    return IndexManifest(**values)


def test_a_manifest_records_everything_that_invalidates_an_index():
    manifest = _manifest()

    assert manifest.chunking_version == CHUNKING_VERSION
    assert manifest.embedding_dimensions > 0


def test_a_manifest_rejects_zero_dimensions():
    with pytest.raises(ValidationError):
        _manifest(embedding_dimensions=0)


def test_a_manifest_rejects_an_unknown_field():
    with pytest.raises(ValidationError):
        _manifest(surprise=True)


def test_chunk_count_may_be_zero_but_not_negative():
    assert _manifest(chunk_count=0).chunk_count == 0
    with pytest.raises(ValidationError):
        _manifest(chunk_count=-1)


# --------------------------------------------------------------------------
# retrieval status: the three outcomes must not collapse
# --------------------------------------------------------------------------

def _hit() -> Hit:
    text = "Increase weekly volume gradually."
    return Hit(
        chunk_id=chunk_id("training-load.md", "Progressive overload", 0),
        content_hash=content_hash(text),
        source="training-load.md",
        heading="Progressive overload",
        text=text,
        rank=1,
    )


def test_ok_requires_at_least_one_hit():
    with pytest.raises(ValidationError, match="at least one hit"):
        RetrievalResult(status="ok", release_id="r1", retrieval_mode="vector")


def test_insufficient_must_not_carry_hits():
    """Filling an empty result with the nearest chunks is the defect being designed out."""
    with pytest.raises(ValidationError, match="must not carry hits"):
        RetrievalResult(status="insufficient", hits=[_hit()], fallback_reason="none")


def test_unavailable_must_not_carry_hits():
    with pytest.raises(ValidationError):
        RetrievalResult(status="unavailable", hits=[_hit()], fallback_reason="index_error")


def test_a_non_ok_status_has_no_retrieval_mode():
    with pytest.raises(ValidationError, match="no successful retrieval mode"):
        RetrievalResult(status="insufficient", retrieval_mode="vector")


def test_found_builds_an_ok_result():
    result = RetrievalResult.found(hits=[_hit()], release_id="release-0001")

    assert result.status == "ok"
    assert result.release_id == "release-0001"


def test_insufficient_and_unavailable_are_distinguishable():
    empty = RetrievalResult.insufficient(release_id="r1")
    broken = RetrievalResult.unavailable(reason="index_unreadable")

    assert empty.status != broken.status
    assert empty.hits == broken.hits == []
    assert empty.fallback_reason == "no_matching_chunk"
    assert broken.fallback_reason == "index_unreadable"


# --------------------------------------------------------------------------
# the fixed corpus
# --------------------------------------------------------------------------

def test_the_corpus_loads_and_is_versioned():
    corpus = _corpus()

    assert corpus.version == "rag-corpus-v1"
    assert len(corpus.cases) >= 8


def test_every_declared_locator_exists_in_the_corpus():
    """A case that cites a chunk nobody wrote cannot be scored."""
    corpus = _corpus()
    present = set()
    for document in corpus.documents:
        heading = "Overview"
        for line in str(document["text"]).splitlines():
            if line.startswith("#"):
                heading = line.lstrip("#").strip() or "Overview"
                present.add(locator(str(document["source"]), heading))
    for case in corpus.cases:
        for value in case.relevant_chunk_ids:
            assert value in present, f"{case.case_id} cites missing {value}"


def test_dev_and_holdout_are_both_present():
    splits = {case.split for case in _corpus().cases}

    assert splits == {"dev", "holdout"}


def test_the_corpus_covers_the_required_categories():
    corpus = _corpus()
    queries = " ".join(case.query for case in corpus.cases)
    documents = " ".join(str(d["text"]) for d in corpus.documents)

    # Long single line: one document has a block far longer than the 900-char chunk cap.
    assert max(len(line) for d in corpus.documents for line in str(d["text"]).splitlines()) > 900
    # Same file, several evidence blocks.
    assert len([c for c in corpus.cases
                if any(loc.startswith("multi-evidence.md#") for loc in c.relevant_chunk_ids)]) >= 1
    # Conflicting sources about the same question.
    assert any(c.case_id == "dev-conflict" and len(c.relevant_chunk_ids) == 2
               for c in corpus.cases)
    # Bilingual synonym queries.
    assert {c.language for c in corpus.cases} == {"zh-CN", "en-US"}
    # Injection text living in the corpus body.
    assert "Ignore all previous instructions" in documents
    # Off-topic and missing-evidence cases.
    assert any(c.should_refuse for c in corpus.cases)
    assert any(c.should_clarify for c in corpus.cases)
    # Unrelated phrasing present.
    assert "股票" in queries


def test_a_case_cannot_declare_a_foreign_corpus_version():
    payload = _corpus_payload()
    payload["cases"][0]["corpus_version"] = "rag-corpus-v2"

    with pytest.raises(ValidationError, match="corpus_version"):
        RetrievalCorpus.model_validate(payload)


def test_case_ids_are_unique():
    payload = _corpus_payload()
    payload["cases"].append(dict(payload["cases"][0]))

    with pytest.raises(ValidationError, match="unique"):
        RetrievalCorpus.model_validate(payload)


def test_a_refusal_case_may_not_cite_evidence():
    with pytest.raises(ValidationError, match="must not declare relevant chunks"):
        QueryCase(case_id="x", corpus_version="v", query="q", split="dev",
                  should_refuse=True, relevant_chunk_ids=["a.md#H"])


def test_a_supported_case_must_cite_evidence():
    with pytest.raises(ValidationError, match="must declare its relevant chunks"):
        QueryCase(case_id="x", corpus_version="v", query="q", split="dev")


def test_a_locator_that_is_not_source_hash_is_rejected():
    with pytest.raises(ValidationError, match="locator"):
        QueryCase(case_id="x", corpus_version="v", query="q", split="dev",
                  relevant_chunk_ids=["not-a-locator"])


def test_corpus_digest_ignores_document_order_but_not_content():
    first = {"source": "a.md", "text": "alpha"}
    second = {"source": "b.md", "text": "beta"}

    assert corpus_digest([first, second]) == corpus_digest([second, first])
    assert corpus_digest([first, second]) != corpus_digest(
        [first, {"source": "b.md", "text": "gamma"}])


def test_normalisation_collapses_horizontal_space_but_keeps_lines():
    assert normalise_text("a   b\u3000c") == "a b c"
    assert normalise_text("line one\nline two") == "line one\nline two"


# --------------------------------------------------------------------------
# known defects, reproduced (RED evidence for R1/R2)
# --------------------------------------------------------------------------

def test_old_entry_still_returns_a_plain_list():
    """The compatibility contract: callers that only want chunks keep working."""
    from backend.rag.retriever import retrieve_knowledge

    result = retrieve_knowledge("progressive overload", top_k=2,
                                index_path=_tmp_index_path())

    assert isinstance(result, list)
    assert all(isinstance(item, dict) for item in result)


def _tmp_index_path() -> Path:
    import tempfile

    return Path(tempfile.mkdtemp()) / "index.json"


def test_a_long_line_is_not_truncated():
    """GAP 1, fixed in R1: the 2000-character line survives reassembly intact."""
    from backend.rag.ingest import chunk_markdown

    long_line = "A" * 2000
    chunks = chunk_markdown({"source": "long.md", "text": "# Heading\n" + long_line})
    recovered = "".join(chunk["text"] for chunk in chunks)

    assert recovered.count("A") == 2000


def test_a_same_length_content_change_invalidates_the_index():
    """GAP 2, fixed in R2: v2 says 'zzz' and the index must serve 'zzz', not v1's 'xxx'."""
    from backend.rag.ingest import chunk_markdown
    from backend.rag.retriever import _load_or_build_index
    from backend.rag.vector_store import build_embedding_provider

    provider = build_embedding_provider()
    index_path = _tmp_index_path()
    v1 = chunk_markdown({"source": "a.md", "text": "# A\n" + "x" * 100 + "\n# B\n" + "y" * 100})
    v2 = chunk_markdown({"source": "a.md", "text": "# A\n" + "z" * 100 + "\n# B\n" + "w" * 100})
    _load_or_build_index(v1, provider=provider, index_path=index_path)
    index = _load_or_build_index(v2, provider=provider, index_path=index_path)

    assert index.entries[0]["chunk"]["text"].startswith("z")


def test_an_unmatched_query_returns_no_content():
    """GAP 3, fixed in R3: an unrelated query returns nothing, not three chunks."""
    from backend.rag.retriever import retrieve_knowledge

    result = retrieve_knowledge("quantum chromodynamics gluon confinement", top_k=3,
                                index_path=_tmp_index_path())

    assert result == []
