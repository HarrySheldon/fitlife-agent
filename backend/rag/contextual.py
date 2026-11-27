"""Index-time contextual retrieval prefix generation and caching."""
from __future__ import annotations

from typing import Any, Mapping, Protocol


def effective_search_text(chunk: Mapping[str, Any]) -> str:
    """Text seen by vector embedding and BM25 lexical indexing.

    When no ``context_prefix`` is attached, returns ``chunk['text']`` verbatim so
    raw-chunk indexing callers remain unaffected.
    """
    prefix = str(chunk.get("context_prefix") or "").strip()
    body = str(chunk.get("text") or "")
    if not prefix:
        return body
    return f"{prefix}\n{body}" if body else prefix


class ContextPrefixGenerator(Protocol):
    mode: str

    def generate(self, chunk: Mapping[str, Any], document: Mapping[str, Any] | None = None) -> str:
        ...


class DeterministicContextPrefixGenerator:
    """Zero-cost deterministic prefix carrying document, section, domain and validity."""

    mode = "deterministic"

    def generate(self, chunk: Mapping[str, Any], document: Mapping[str, Any] | None = None) -> str:
        source = str(chunk.get("source") or (document or {}).get("source") or "unknown")
        heading = str(chunk.get("heading") or "Overview")
        domain = str(chunk.get("domain") or (document or {}).get("domain") or "general")
        doc_type = str(chunk.get("doc_type") or (document or {}).get("doc_type") or "markdown")
        policy_version = chunk.get("policy_version") or (document or {}).get("policy_version")
        parts = [f"来源: {source}", f"章节: {heading}", f"领域: {domain}", f"类型: {doc_type}"]
        if policy_version:
            parts.append(f"版本: {policy_version}")
        return "[" + " | ".join(parts) + "]"


class OpenAIContextPrefixGenerator:
    """LLM-based index-time contextual prefix generator via structured/chat gateway."""

    mode = "llm"

    def __init__(self, *, client: Any, model: str) -> None:
        self.client = client
        self.model = model
        self._fallback = DeterministicContextPrefixGenerator()

    def generate(self, chunk: Mapping[str, Any], document: Mapping[str, Any] | None = None) -> str:
        source = str(chunk.get("source") or (document or {}).get("source") or "")
        heading = str(chunk.get("heading") or "Overview")
        doc_excerpt = str((document or {}).get("text") or "")[:1200]
        prompt = (
            f"Document: {source}\nSection: {heading}\n"
            f"Excerpt:\n{doc_excerpt}\n\n"
            f"Chunk:\n{chunk.get('text', '')}\n\n"
            "Write 1 concise sentence (under 40 words) placing this chunk within the document "
            "for retrieval indexing. Return only that context sentence."
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You generate concise retrieval context prefixes."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=96,
            )
            text = str(response.choices[0].message.content or "").strip()
            if text:
                return text[:240]
        except Exception:
            pass
        return self._fallback.generate(chunk, document)


def build_context_prefix_generator(settings: Any = None, *, client: Any = None) -> ContextPrefixGenerator | None:
    if settings is None:
        from backend.config import get_settings

        settings = get_settings()
    mode = getattr(settings, "rag_contextual_prefix_mode", "deterministic") or "deterministic"
    if mode == "off":
        return None
    if mode == "llm":
        if client is None and getattr(settings, "openai_api_key", None):
            try:
                from openai import OpenAI

                kwargs: dict[str, str] = {"api_key": settings.openai_api_key}
                if getattr(settings, "openai_base_url", None):
                    kwargs["base_url"] = settings.openai_base_url
                client = OpenAI(**kwargs)
            except ImportError:
                client = None
        if client is not None:
            return OpenAIContextPrefixGenerator(client=client, model=settings.openai_model)
    return DeterministicContextPrefixGenerator()


def apply_contextual_prefixes(
    chunks: list[dict[str, Any]],
    documents: list[Mapping[str, Any]] | None = None,
    *,
    generator: ContextPrefixGenerator | None,
    cached_prefixes: Mapping[tuple[str, str], str] | None = None,
) -> list[dict[str, Any]]:
    """Attach ``context_prefix`` to chunks, reusing cache hits keyed by content & doc version."""
    if generator is None:
        return [dict(chunk) for chunk in chunks]

    docs_by_source = {str(doc.get("source", "")): doc for doc in (documents or ())}
    cache = cached_prefixes or {}
    out: list[dict[str, Any]] = []
    for chunk in chunks:
        if chunk.get("context_prefix"):
            out.append(dict(chunk))
            continue
        cache_key = (str(chunk.get("content_hash") or ""), str(chunk.get("document_version") or ""))
        prefix = cache.get(cache_key)
        if not prefix:
            prefix = generator.generate(chunk, docs_by_source.get(str(chunk.get("source") or "")))
        enriched = dict(chunk)
        if prefix:
            enriched["context_prefix"] = prefix
        out.append(enriched)
    return out
