# Vector RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade FitLife Agent's knowledge retrieval from token-overlap scoring to an embedding-backed vector index while preserving offline demo behavior.

**Architecture:** `backend/rag/vector_store.py` owns embedding providers, cosine similarity, vector index construction, JSON persistence, and search. `backend/rag/retriever.py` loads knowledge chunks, builds or reuses a vector index, returns source-diverse chunks, and falls back to lexical scoring if vector search is unavailable.

**Tech Stack:** Python stdlib, OpenAI Python SDK for optional embeddings, pytest.

---

## References

- OpenAI Python SDK embeddings API: `client.embeddings.create(model=..., input=...)`, with vectors read from `response.data[0].embedding`.
- Existing project config: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `EMBEDDING_MODEL`.
- Existing RAG contract: `retrieve_knowledge(query: str, top_k: int) -> list[dict]`.

## Acceptance Criteria

- Vector search is deterministic and testable without network access.
- A local hashing embedding provider is the default provider for demo/test mode.
- An optional OpenAI embedding provider can be built when `OPENAI_API_KEY` is available.
- `VectorIndex` can:
  - build entries from knowledge chunks;
  - compute cosine similarity;
  - return ranked chunks;
  - save to and load from JSON.
- `retrieve_knowledge()` still returns chunk dicts with `source`, `heading`, and `text`.
- Retrieval remains source-diverse and eval-compatible.
- Existing backend tests and 5-case eval smoke still pass.

## Files

- Modify: `backend/rag/vector_store.py`
  - Add `EmbeddingProvider`, `HashingEmbeddingProvider`, `OpenAIEmbeddingProvider`, `VectorIndex`, cosine similarity, and JSON persistence.
  - Keep `tokenize()` and `score_text()` for lexical fallback.
- Modify: `backend/rag/retriever.py`
  - Use vector search first.
  - Keep source diversity and lexical fallback.
- Modify: `backend/config.py`
  - Add `vector_index_path`.
- Modify: `.env.example`
  - Keep `EMBEDDING_MODEL` documented.
- Test: `backend/tests/test_vector_store.py`
  - Hashing embeddings are deterministic and normalized.
  - Vector index ranks semantically matching chunks.
  - Vector index round-trips through JSON.
  - OpenAI provider calls `client.embeddings.create()` with expected parameters.
- Test: `backend/tests/test_retriever.py`
  - Existing source metadata and meal replacement retrieval continue to pass.
  - Add a test proving vector retriever preserves source diversity.

## TDD Steps

1. Write failing vector store tests in `backend/tests/test_vector_store.py`.
2. Run `pytest backend\tests\test_vector_store.py -q -p no:cacheprovider` and verify failures.
3. Implement vector store primitives.
4. Run vector store tests until green.
5. Add retriever integration tests for vector search and source diversity.
6. Update `backend/rag/retriever.py` to use `VectorIndex`.
7. Run retriever tests.
8. Run full backend tests and eval smoke:

```powershell
..\..\.venv\Scripts\python -m pytest backend\tests -q -p no:cacheprovider
..\..\.venv\Scripts\python scripts\run_eval.py --limit 5
```

9. Commit and push `feat/vector-rag`.
