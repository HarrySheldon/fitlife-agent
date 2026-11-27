"""Chunk-level RAG evaluation (Recall@5, MRR, nDCG@k, validity & unanswerable) and ablation CLI."""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from backend.config import BACKEND_ROOT, get_settings
from backend.rag.bm25 import BM25Index
from backend.rag.contextual import DeterministicContextPrefixGenerator, apply_contextual_prefixes
from backend.rag.contracts import Hit, RetrievalResult, chunk_id, content_hash, document_version
from backend.rag.ingest import chunk_markdown, ensure_chunk_identity, load_markdown_documents
from backend.rag.query_router import classify_query
from backend.rag.ranking import fuse, rerank, select_with_diversity
from backend.rag.reranker import LexicalCrossReranker
from backend.rag.retriever import _filter_release_chunks, _query_is_wordlike, is_chunk_valid_at, retrieve_detailed
from backend.rag.vector_store import HashingEmbeddingProvider, VectorIndex, score_text

DEFAULT_DATASET_PATH = BACKEND_ROOT / "data" / "rag_eval_dataset.json"
DEFAULT_GATE_THRESHOLDS = {
    "recall_at_5": 0.80,
    "mrr": 0.70,
    "ndcg_at_5": 0.70,
    "expired_filter_accuracy": 1.0,
    "unanswerable_rejection_rate": 0.85,
}


def hit_locator(hit: Hit | Mapping[str, Any]) -> str:
    source = hit["source"] if isinstance(hit, Mapping) else hit.source
    heading = hit["heading"] if isinstance(hit, Mapping) else hit.heading
    return f"{source}#{heading}"


def compute_recall_at_k(retrieved_locators: Sequence[str], relevant: Mapping[str, int], k: int = 5) -> float:
    positives = {loc for loc, rel in relevant.items() if rel > 0}
    if not positives:
        return 0.0
    unique_top = list(dict.fromkeys(retrieved_locators))[:k]
    matched = sum(1 for loc in positives if loc in unique_top)
    return matched / len(positives)


def compute_mrr(retrieved_locators: Sequence[str], relevant: Mapping[str, int]) -> float:
    positives = {loc for loc, rel in relevant.items() if rel > 0}
    if not positives:
        return 0.0
    for rank, loc in enumerate(retrieved_locators, start=1):
        if loc in positives:
            return 1.0 / rank
    return 0.0


def compute_ndcg_at_k(retrieved_locators: Sequence[str], relevant: Mapping[str, int], k: int = 5) -> float:
    ideal_grades = sorted((int(rel) for rel in relevant.values() if rel > 0), reverse=True)[:k]
    if not ideal_grades:
        return 0.0
    idcg = sum(((2 ** rel) - 1) / math.log2(rank + 1) for rank, rel in enumerate(ideal_grades, start=1))
    if idcg <= 0:
        return 0.0
    seen: set[str] = set()
    dcg = 0.0
    for rank, loc in enumerate(list(retrieved_locators)[:k], start=1):
        if loc in seen:
            continue
        seen.add(loc)
        rel = max(0, int(relevant.get(loc, 0)))
        if rel > 0:
            dcg += ((2 ** rel) - 1) / math.log2(rank + 1)
    return min(1.0, dcg / idcg)


@dataclass(frozen=True)
class RagMetricsSummary:
    variant: str
    total_cases: int
    positive_cases: int
    validity_cases: int
    unanswerable_cases: int
    recall_at_5: float
    hit_rate_at_5: float
    mrr: float
    ndcg_at_5: float
    ndcg_at_10: float
    expired_filter_accuracy: float
    unanswerable_rejection_rate: float


def load_rag_eval_dataset(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else DEFAULT_DATASET_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def _build_variant_chunks(*, documents: list[dict], overlap_ratio: float, contextual: bool) -> list[dict]:
    chunks: list[dict] = []
    for doc in documents:
        chunks.extend(chunk_markdown(doc, max_chars=900, overlap_ratio=overlap_ratio))
    chunks = ensure_chunk_identity(chunks)
    if contextual:
        chunks = apply_contextual_prefixes(
            chunks,
            documents,
            generator=DeterministicContextPrefixGenerator(),
        )
    return chunks


def _run_memory_variant(variant: str, cases: list[dict[str, Any]], *, kb_dir: Path | None = None) -> list[tuple[dict[str, Any], RetrievalResult]]:
    documents = load_markdown_documents(kb_dir)
    provider = HashingEmbeddingProvider()

    if variant == "dense_only":
        chunks = _build_variant_chunks(documents=documents, overlap_ratio=0.0, contextual=False)
        index = VectorIndex.build(chunks, provider=provider)
        use_dense, use_bm25, use_rerank, use_filters = True, False, False, False
    elif variant == "bm25_only":
        chunks = _build_variant_chunks(documents=documents, overlap_ratio=0.0, contextual=False)
        index = None
        use_dense, use_bm25, use_rerank, use_filters = False, True, False, False
    elif variant == "hybrid_rrf":
        chunks = _build_variant_chunks(documents=documents, overlap_ratio=0.15, contextual=False)
        index = VectorIndex.build(chunks, provider=provider)
        use_dense, use_bm25, use_rerank, use_filters = True, True, False, True
    elif variant == "hybrid_rrf_rerank_contextual":
        chunks = _build_variant_chunks(documents=documents, overlap_ratio=0.15, contextual=True)
        index = VectorIndex.build(chunks, provider=provider)
        use_dense, use_bm25, use_rerank, use_filters = True, True, True, True
    else:
        raise ValueError(f"Unknown RAG evaluation variant: {variant!r}")

    reranker = LexicalCrossReranker() if use_rerank else None
    outcomes: list[tuple[dict[str, Any], RetrievalResult]] = []
    for case in cases:
        query = str(case["query"])
        scope = case.get("scope")
        as_of = date.fromisoformat(case["as_of"]) if case.get("as_of") else date(2026, 11, 27)
        if use_filters:
            qplan = classify_query(query, explicit_scope=scope)
            pool, allowed_ids = _filter_release_chunks(
                chunks,
                as_of=as_of,
                domain=qplan.domain,
                strict_filter=qplan.strict_filter,
                extra_filters=None,
            )
        else:
            pool = list(chunks)
            allowed_ids = {c["chunk_id"] for c in pool}

        lists: list[list[Hit]] = []
        if use_dense and index is not None:
            raw_vec = index.search(query, provider=provider, top_k=len(chunks))
            filtered_vec = [item for item in raw_vec if item["chunk_id"] in allowed_ids]
            lists.append([
                Hit(
                    chunk_id=item["chunk_id"],
                    content_hash=item["content_hash"],
                    source=item["source"],
                    heading=item["heading"],
                    text=item["text"],
                    rank=pos,
                    score=float(item.get("score") or 0.0),
                )
                for pos, item in enumerate(filtered_vec, start=1)
            ])
        if use_bm25:
            bm25_scored = BM25Index(pool).score_all(query)
            if not bm25_scored:
                outcomes.append((case, RetrievalResult.insufficient(release_id="eval-memory")))
                continue
            lists.append([
                Hit(
                    chunk_id=item["chunk_id"],
                    content_hash=item["content_hash"],
                    source=item["source"],
                    heading=item["heading"],
                    text=item["text"],
                    rank=pos,
                    score=score,
                )
                for pos, (score, item) in enumerate(bm25_scored, start=1)
            ])
        else:
            # Lexical gate prevents off-topic queries from surfacing unrelated vector hits.
            if not BM25Index(pool).score_all(query):
                outcomes.append((case, RetrievalResult.insufficient(release_id="eval-memory")))
                continue

        fused = fuse(lists)
        picked = select_with_diversity(fused, top_k=10, per_source_cap=3)
        rr = rerank(query, picked, reranker=reranker)
        hits = [
            Hit(
                chunk_id=item.chunk_id,
                content_hash=item.content_hash,
                source=item.source,
                heading=item.heading,
                text=item.text,
                rank=pos,
                score=item.score,
            )
            for pos, item in enumerate(rr.hits, start=1)
        ]
        if not hits:
            outcomes.append((case, RetrievalResult.insufficient(release_id="eval-memory")))
        else:
            mode = "reranked" if rr.applied else ("hybrid" if len(lists) > 1 else ("bm25" if use_bm25 else "vector"))
            outcomes.append((case, RetrievalResult.found(hits=hits, release_id="eval-memory", retrieval_mode=mode if mode != "bm25" else "lexical")))
    return outcomes


def _run_postgres_variant(
    variant: str,
    cases: list[dict[str, Any]],
    *,
    database_url: str,
) -> list[tuple[dict[str, Any], RetrievalResult]]:
    from backend.infrastructure.postgres.database import PostgresDatabase
    from backend.infrastructure.postgres.runtime import ensure_database_ready
    from backend.rag import ingest as ingest_mod, retriever as retriever_mod

    schema = f"rag_eval_{uuid4().hex[:10]}"
    db = PostgresDatabase(database_url, schema=schema)
    db.create_schema()
    ensure_database_ready(db)
    provider = HashingEmbeddingProvider()
    orig_loader = retriever_mod.load_knowledge_chunks
    try:
        if variant == "hybrid_rrf_rerank_contextual":
            retriever_mod.clear_index_cache()
            retriever_mod.load_knowledge_chunks = lambda: ingest_mod.load_knowledge_chunks(
                overlap_ratio=0.15, contextual_mode="deterministic"
            )
            retriever_mod.build_knowledge_index(provider=provider, database=db)
            reranker = LexicalCrossReranker()
        elif variant == "hybrid_rrf":
            retriever_mod.clear_index_cache()
            retriever_mod.load_knowledge_chunks = lambda: ingest_mod.load_knowledge_chunks(
                overlap_ratio=0.15, contextual_mode="off"
            )
            retriever_mod.build_knowledge_index(provider=provider, database=db)
            reranker = None
        else:
            return _run_memory_variant(variant, cases)

        outcomes: list[tuple[dict[str, Any], RetrievalResult]] = []
        for case in cases:
            as_of = date.fromisoformat(case["as_of"]) if case.get("as_of") else date(2026, 11, 27)
            res = retrieve_detailed(
                str(case["query"]),
                top_k=10,
                provider=provider,
                database=db,
                reranker=reranker,
                per_source_cap=3,
                allow_build=False,
                scope=case.get("scope"),
                as_of=as_of,
                use_reranker=reranker is not None,
            )
            outcomes.append((case, res))
        return outcomes
    finally:
        retriever_mod.load_knowledge_chunks = orig_loader
        retriever_mod.clear_index_cache()
        try:
            db.drop_schema()
        except Exception:
            pass


def score_variant(variant: str, outcomes: Sequence[tuple[dict[str, Any], RetrievalResult]]) -> RagMetricsSummary:
    recalls: list[float] = []
    hit_5s: list[float] = []
    mrrs: list[float] = []
    ndcg5s: list[float] = []
    ndcg10s: list[float] = []
    validity_checks: list[bool] = []
    unanswerable_checks: list[bool] = []

    for case, result in outcomes:
        relevant = {str(k): int(v) for k, v in (case.get("relevant") or {}).items()}
        locators = [hit_locator(hit) for hit in result.hits]
        top5_sources = {hit.source for hit in result.hits[:5]}

        if relevant:
            recalls.append(compute_recall_at_k(locators, relevant, k=5))
            hit_5s.append(1.0 if any(loc in relevant for loc in locators[:5]) else 0.0)
            mrrs.append(compute_mrr(locators, relevant))
            ndcg5s.append(compute_ndcg_at_k(locators, relevant, k=5))
            ndcg10s.append(compute_ndcg_at_k(locators, relevant, k=10))

        excluded = set(case.get("excluded_sources") or ())
        if excluded:
            validity_checks.append(not bool(excluded & top5_sources))

        if case.get("expect_insufficient"):
            unanswerable_checks.append(result.status == "insufficient" or len(result.hits) == 0)

    def mean(values: list[float], default: float = 0.0) -> float:
        return round(sum(values) / len(values), 4) if values else default

    return RagMetricsSummary(
        variant=variant,
        total_cases=len(outcomes),
        positive_cases=len(recalls),
        validity_cases=len(validity_checks),
        unanswerable_cases=len(unanswerable_checks),
        recall_at_5=mean(recalls),
        hit_rate_at_5=mean(hit_5s),
        mrr=mean(mrrs),
        ndcg_at_5=mean(ndcg5s),
        ndcg_at_10=mean(ndcg10s),
        expired_filter_accuracy=round(sum(validity_checks) / len(validity_checks), 4) if validity_checks else 1.0,
        unanswerable_rejection_rate=round(sum(unanswerable_checks) / len(unanswerable_checks), 4) if unanswerable_checks else 1.0,
    )


def evaluate_ablation(
    *,
    backend: str = "memory",
    dataset_path: str | Path | None = None,
    database_url: str | None = None,
) -> list[RagMetricsSummary]:
    dataset = load_rag_eval_dataset(dataset_path)
    cases = list(dataset["cases"])
    variants = ("dense_only", "bm25_only", "hybrid_rrf", "hybrid_rrf_rerank_contextual")
    summaries: list[RagMetricsSummary] = []
    for variant in variants:
        if backend == "postgres":
            dsn = database_url or get_settings().database_url
            outcomes = _run_postgres_variant(variant, cases, database_url=dsn)
        else:
            outcomes = _run_memory_variant(variant, cases)
        summaries.append(score_variant(variant, outcomes))
    return summaries


def check_gate(summary: RagMetricsSummary, thresholds: Mapping[str, float] = DEFAULT_GATE_THRESHOLDS) -> list[str]:
    failures: list[str] = []
    for metric, minimum in thresholds.items():
        observed = float(getattr(summary, metric))
        if observed < minimum:
            failures.append(f"{summary.variant}.{metric}={observed:.4f} < {minimum:.4f}")
    return failures


def render_ablation_markdown(summaries: Sequence[RagMetricsSummary]) -> str:
    lines = [
        "| Variant | Recall@5 | Hit@5 | MRR | nDCG@5 | nDCG@10 | ExpiredFilter | UnanswerableRej |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in summaries:
        lines.append(
            f"| {s.variant} | {s.recall_at_5:.4f} | {s.hit_rate_at_5:.4f} | {s.mrr:.4f} | "
            f"{s.ndcg_at_5:.4f} | {s.ndcg_at_10:.4f} | {s.expired_filter_accuracy:.4f} | {s.unanswerable_rejection_rate:.4f} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run FitLife chunk-level RAG ablation evaluation")
    parser.add_argument("--backend", choices=("memory", "postgres"), default="memory")
    parser.add_argument("--database-url", type=str, default=None)
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--gate", action="store_true")
    args = parser.parse_args(argv)

    summaries = evaluate_ablation(
        backend=args.backend,
        dataset_path=args.dataset,
        database_url=args.database_url,
    )
    target = summaries[-1]
    failures = check_gate(target)
    payload = {
        "backend": args.backend,
        "target_variant": target.variant,
        "gate_passed": not failures,
        "gate_failures": failures,
        "summaries": [asdict(s) for s in summaries],
    }
    print(render_ablation_markdown(summaries))
    print(json.dumps(payload, ensure_ascii=False))
    if args.gate and failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
