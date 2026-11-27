"""Tests for Step 1.3 hybrid RAG upgrade: parsers, overlap, contextual prefix, BM25, BGE, validity, eval."""
from __future__ import annotations

from datetime import date
from io import BytesIO
import json
from pathlib import Path

import httpx
import pytest
from pypdf import PdfReader, PdfWriter

from backend.rag.bm25 import BM25Index, tokenize_bm25
from backend.rag.contextual import (
    DeterministicContextPrefixGenerator,
    apply_contextual_prefixes,
    effective_search_text,
)
from backend.rag.contracts import CHUNKING_VERSION, Hit, chunk_id, content_hash
from backend.rag.evaluation import (
    check_gate,
    compute_mrr,
    compute_ndcg_at_k,
    compute_recall_at_k,
    evaluate_ablation,
)
from backend.rag.ingest import chunk_markdown, load_markdown_documents
from backend.rag.parsers import load_document_from_path, parse_frontmatter, parse_pdf_document
from backend.rag.query_router import classify_query
from backend.rag.ranking import rerank
from backend.rag.reranker import BgeReranker, LexicalCrossReranker
from backend.rag.retriever import is_chunk_valid_at
from backend.rag.vector_store import BgeM3EmbeddingProvider


def _build_minimal_pdf_bytes(text: str) -> bytes:
    """Create a valid minimal single-page PDF byte stream containing ASCII ``text``."""
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET\n".encode("latin-1")
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
        ),
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        (
            f"5 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("latin-1")
            + stream
            + b"endstream\nendobj\n"
        ),
    ]
    buf = BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets: list[int] = [0]
    for obj in objects:
        offsets.append(buf.tell())
        buf.write(obj)
    xref_pos = buf.tell()
    buf.write(f"xref\n0 {len(offsets)}\n".encode("latin-1"))
    buf.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buf.write(f"{offset:010d} 00000 n \n".encode("latin-1"))
    buf.write(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "latin-1"
        )
    )
    return buf.getvalue()


def test_parse_frontmatter_preserves_metadata_without_fabricating_missing():
    raw = (
        "---\n"
        "domain: nutrition\n"
        "valid_from: 2026-01-01\n"
        "policy_version: 2026.1\n"
        "---\n"
        "## 蛋白替代\n鸡胸肉 100g 可替换为去皮鸡腿肉 115g。\n"
    )
    meta, body = parse_frontmatter(raw)
    assert meta == {
        "domain": "nutrition",
        "valid_from": "2026-01-01",
        "policy_version": "2026.1",
    }
    assert "source_url" not in meta
    assert "expires_at" not in meta
    assert body.startswith("## 蛋白替代")

    chunks = chunk_markdown(
        {
            "source": "macro_swap.md",
            "text": body,
            **meta,
        },
        max_chars=180,
        overlap_ratio=0.15,
    )
    assert len(chunks) == 1
    assert chunks[0]["domain"] == "nutrition"
    assert chunks[0]["valid_from"] == "2026-01-01"
    assert chunks[0]["policy_version"] == "2026.1"
    assert chunks[0].get("expires_at") is None
    assert chunks[0]["source_url"] is None


def test_parse_pdf_document_and_load_document_from_path(tmp_path: Path):
    pdf_path = tmp_path / "training_guide.pdf"
    pdf_bytes = _build_minimal_pdf_bytes("FitLife Progressive Overload Guide")
    # Sanity verify PdfWriter/PdfReader accepts the payload.
    assert len(PdfReader(BytesIO(pdf_bytes)).pages) == 1
    assert len(PdfWriter().pages) == 0

    pdf_path.write_bytes(pdf_bytes)
    doc = parse_pdf_document(pdf_path)
    assert doc["doc_type"] == "pdf"
    assert doc["domain"] == "training"
    assert "## Page 1" in doc["text"]
    assert "FitLife Progressive Overload Guide" in doc["text"]

    loaded = load_document_from_path(pdf_path)
    assert loaded["source"] == "training_guide.pdf"
    chunks = chunk_markdown(loaded, max_chars=240)
    assert chunks
    assert chunks[0]["doc_type"] == "pdf"
    assert chunks[0]["domain"] == "training"


def test_table_chunking_repeats_headers_and_marks_doc_type_table():
    table_doc = {
        "source": "macro_substitution_tables.md",
        "domain": "nutrition",
        "text": (
            "## 常见蛋白质等量替换表\n"
            "| 食物 | 份量 | 蛋白质(g) |\n"
            "| --- | --- | --- |\n"
            "| 鸡胸肉 | 100g | 23 |\n"
            "| 低脂牛肉 | 110g | 23 |\n"
            "| 鳕鱼 | 130g | 23 |\n"
            "| 北豆腐 | 220g | 22 |\n"
            "| 乳清蛋白粉 | 30g | 24 |\n"
        ),
    }
    chunks = chunk_markdown(table_doc, max_chars=115, overlap_ratio=0.15)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk["doc_type"] == "table"
        assert chunk["chunking_version"] == CHUNKING_VERSION
        assert len(chunk["text"]) <= 115
        lines = chunk["text"].splitlines()
        assert lines[0] == "| 食物 | 份量 | 蛋白质(g) |"
        assert lines[1] == "| --- | --- | --- |"


def test_prose_overlap_carries_context_within_max_chars_and_default_stays_zero_overlap():
    text = "## 长段落\n" + "。".join(f"第{i}条训练建议强调控制离心速度与呼吸节奏" for i in range(1, 12)) + "。"
    no_overlap = chunk_markdown({"source": "notes.md", "text": text}, max_chars=140)
    with_overlap = chunk_markdown(
        {"source": "notes.md", "text": text},
        max_chars=140,
        overlap_ratio=0.15,
    )
    assert len(no_overlap) >= 2
    assert len(with_overlap) == len(no_overlap)
    assert all(len(c["text"]) <= 140 for c in with_overlap)
    tail_snippet = no_overlap[0]["text"][-10:]
    assert tail_snippet in with_overlap[1]["text"]
    assert no_overlap[1]["text"] in with_overlap[1]["text"]


def test_contextual_prefix_generation_cache_and_effective_search_text():
    raw_chunk = {
        "chunk_id": "doc#Overview#0:abcd",
        "content_hash": "hash-1",
        "source": "nutrition_guidelines.md",
        "heading": "蛋白质目标",
        "domain": "nutrition",
        "doc_type": "markdown",
        "policy_version": "2026.1",
        "text": "减脂期推荐每日每公斤体重摄入 1.6 到 2.2 克蛋白质。",
    }
    assert effective_search_text(raw_chunk) == raw_chunk["text"]

    calls = 0

    class CountingGenerator:
        mode = "deterministic"

        def __init__(self) -> None:
            self._inner = DeterministicContextPrefixGenerator()

        def generate(self, chunk, document=None) -> str:
            nonlocal calls
            calls += 1
            return self._inner.generate(chunk, document)

    enriched = apply_contextual_prefixes(
        [raw_chunk],
        generator=CountingGenerator(),
        cached_prefixes={},
    )
    assert calls == 1
    assert enriched[0]["context_prefix"]
    assert enriched[0]["context_prefix"] in effective_search_text(enriched[0])

    reused = apply_contextual_prefixes(
        [raw_chunk],
        generator=CountingGenerator(),
        cached_prefixes={("hash-1", ""): enriched[0]["context_prefix"]},
    )
    assert calls == 1
    assert reused[0]["context_prefix"] == enriched[0]["context_prefix"]


def test_chinese_bm25_tokenizer_and_scoring():
    tokens = tokenize_bm25("鸡胸肉 100g 蛋白质 替换 乳清蛋白")
    assert "鸡胸肉" in tokens
    assert "100g" in tokens
    assert "蛋白质" in tokens

    chunks = [
        {
            "chunk_id": "a#0",
            "source": "macro_substitution_tables.md",
            "heading": "蛋白质替换",
            "text": "| 鸡胸肉 | 100g | 23g 蛋白质 | 可替换为 北豆腐 或 乳清蛋白 |",
            "context_prefix": "[来源: macro_substitution_tables.md | 领域: nutrition]",
        },
        {
            "chunk_id": "b#0",
            "source": "training_volume_tables.md",
            "heading": "每周容量",
            "text": "胸肌每周有效组数 10 到 20 组，RPE 控制在 7-9。",
            "context_prefix": "[来源: training_volume_tables.md | 领域: training]",
        },
    ]
    index = BM25Index(chunks)
    ranked = index.score_all("鸡胸肉 100g 怎么替换")
    assert ranked
    assert ranked[0][1]["chunk_id"] == "a#0"


def test_bge_m3_embedding_and_reranker_with_mock_http_and_fallback():
    def embed_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        payload = json.loads(request.read().decode("utf-8"))
        if payload.get("input") == ["a", "b"]:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [0.0, 3.0, 4.0]},
                        {"index": 0, "embedding": [3.0, 4.0, 0.0]},
                    ]
                },
            )
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [6.0, 8.0, 0.0]}]})

    embed_client = httpx.Client(transport=httpx.MockTransport(embed_handler))
    provider = BgeM3EmbeddingProvider(
        base_url="https://api.example.test/v1",
        api_key="test-key",
        client=embed_client,
    )
    q_vec = provider.embed_query("protein target")
    assert q_vec == pytest.approx([0.6, 0.8, 0.0])
    doc_vecs = provider.embed_documents(["a", "b"])
    assert doc_vecs[0] == pytest.approx([0.6, 0.8, 0.0])
    assert doc_vecs[1] == pytest.approx([0.0, 0.6, 0.8])

    def rerank_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rerank")
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.25},
                    {"index": 1, "relevance_score": 0.92},
                ]
            },
        )

    rerank_client = httpx.Client(transport=httpx.MockTransport(rerank_handler))
    bge_reranker = BgeReranker(base_url="https://api.example.test/v1", client=rerank_client)
    id_1 = chunk_id("d1", "Overview", 0)
    id_2 = chunk_id("d2", "拉伤处理", 0)
    hits = [
        Hit(chunk_id=id_1, content_hash=content_hash("普通散步恢复"), source="d1", heading="Overview", text="普通散步恢复", rank=1, score=0.9),
        Hit(chunk_id=id_2, content_hash=content_hash("急性拉伤前48小时遵循保护与冰敷原则"), source="d2", heading="拉伤处理", text="急性拉伤前48小时遵循保护与冰敷原则", rank=2, score=0.5),
    ]
    outcome = rerank("急性拉伤怎么处理", hits, reranker=bge_reranker)
    assert outcome.applied is True
    assert outcome.hits[0].chunk_id == id_2

    lexical_scores = LexicalCrossReranker()("急性拉伤", hits)
    assert lexical_scores[id_2] > lexical_scores[id_1]

    def failing_reranker(_query: str, _hits) -> dict[str, float]:
        raise RuntimeError("upstream unavailable")

    fallback_outcome = rerank("急性拉伤", hits, reranker=failing_reranker)
    assert fallback_outcome.applied is False
    assert fallback_outcome.reason == "reranker_error"
    assert [h.chunk_id for h in fallback_outcome.hits] == [id_1, id_2]


def test_query_router_and_validity_filtering():
    nutrition_plan = classify_query("鸡胸肉 100g 可以替换成什么？")
    assert nutrition_plan.domain == "nutrition"
    assert nutrition_plan.doc_type_hint == "table"
    assert nutrition_plan.strict_filter is False

    scoped_plan = classify_query("一般建议", explicit_scope="training")
    assert scoped_plan.domain == "training"
    assert scoped_plan.strict_filter is True

    expired_chunk = {"chunk_id": "old#0", "valid_from": "2024-01-01", "expires_at": "2024-12-31"}
    future_chunk = {"chunk_id": "future#0", "valid_from": "2027-01-01", "expires_at": "2027-12-31"}
    active_chunk = {"chunk_id": "cur#0", "valid_from": "2025-01-01", "expires_at": None}

    today = date(2026, 6, 1)
    assert is_chunk_valid_at(expired_chunk, today) is False
    assert is_chunk_valid_at(future_chunk, today) is False
    assert is_chunk_valid_at(active_chunk, today) is True
    assert is_chunk_valid_at(expired_chunk, date(2024, 6, 1)) is True

    docs = {doc["source"]: doc for doc in load_markdown_documents()}
    assert "legacy_policy_2024.md" in docs
    assert is_chunk_valid_at(docs["legacy_policy_2024.md"], today) is False


def test_evaluation_metrics_and_memory_ablation_gate():
    locators = ["a#1", "b#2", "c#3", "a#1"]
    relevant = {"b#2": 2, "d#4": 1}
    assert compute_recall_at_k(locators, relevant, k=3) == pytest.approx(0.5)
    assert compute_mrr(locators, relevant) == pytest.approx(0.5)
    ndcg3 = compute_ndcg_at_k(locators, relevant, k=3)
    assert 0.0 < ndcg3 < 1.0
    assert compute_ndcg_at_k(["b#2", "d#4"], relevant, k=2) == pytest.approx(1.0)

    summaries = evaluate_ablation(backend="memory")
    by_name = {s.variant: s for s in summaries}
    full = by_name["hybrid_rrf_rerank_contextual"]
    assert full.total_cases == 64
    assert full.expired_filter_accuracy == 1.0
    assert check_gate(full) == []
    assert full.ndcg_at_5 >= by_name["dense_only"].ndcg_at_5
