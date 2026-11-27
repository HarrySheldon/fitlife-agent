"""Chinese-aware tokenization and Okapi BM25 sparse retrieval index."""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Mapping, Sequence

from backend.rag.contextual import effective_search_text

_ASCII_TOKEN_RE = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)?")
_UPPER_CODE_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_STOPWORDS = frozenset({
    "的", "了", "和", "与", "及", "在", "是", "有", "为", "对", "把", "被", "让", "给",
    "从", "到", "着", "过", "等", "吗", "呢", "吧", "啊", "这", "那", "会", "能", "可以",
    "a", "an", "the", "and", "or", "is", "are", "was", "were", "of", "to", "in", "for", "on", "with",
})

try:
    import jieba
except ImportError:  # pragma: no cover - optional fallback when jieba absent
    jieba = None


def tokenize_bm25(text: str) -> list[str]:
    """Tokenize bilingual Chinese/English fitness text for sparse BM25 matching."""
    lowered = text.lower()
    tokens: list[str] = []
    for tok in _ASCII_TOKEN_RE.findall(lowered):
        if tok not in _STOPWORDS:
            tokens.append(tok)
        if "." in tok or "_" in tok:
            stem = tok.rsplit(".", 1)[0]
            if stem and stem != tok and stem not in _STOPWORDS:
                tokens.append(stem)
            for part in re.split(r"[._]+", tok):
                if len(part) >= 2 and part != tok and part != stem and part not in _STOPWORDS:
                    tokens.append(part)
    if jieba is not None:
        for run in _CJK_RUN_RE.findall(lowered):
            for term in jieba.cut_for_search(run):
                cleaned = term.strip()
                if cleaned and cleaned not in _STOPWORDS:
                    tokens.append(cleaned)
    else:
        for run in _CJK_RUN_RE.findall(lowered):
            tokens.extend(ch for ch in run if ch not in _STOPWORDS)
            if len(run) >= 2:
                tokens.extend(
                    bigram
                    for bigram in (run[i : i + 2] for i in range(len(run) - 1))
                    if bigram not in _STOPWORDS
                )
    return tokens


class BM25Index:
    """Deterministic Okapi BM25 over chunks (content + contextual prefix + heading/source)."""

    def __init__(
        self,
        chunks: Sequence[Mapping[str, Any]],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.chunks = list(chunks)
        self._n = len(self.chunks)
        self._doc_freqs: list[Counter[str]] = []
        self._doc_lengths: list[int] = []
        df: Counter[str] = Counter()

        for chunk in self.chunks:
            searchable = (
                f"{chunk.get('source', '')} {chunk.get('heading', '')} "
                f"{effective_search_text(chunk)}"
            )
            terms = tokenize_bm25(searchable)
            tf = Counter(terms)
            self._doc_freqs.append(tf)
            self._doc_lengths.append(len(terms))
            for term in tf:
                df[term] += 1

        self._avgdl = (sum(self._doc_lengths) / self._n) if self._n else 1.0
        self._idf = {
            term: math.log(1.0 + (self._n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def score_all(self, query: str) -> list[tuple[float, dict[str, Any]]]:
        query_terms = tokenize_bm25(query)
        if not query_terms or not self._n:
            return []
        q_counts = Counter(query_terms)
        required_identifiers = [tok.lower() for tok in _UPPER_CODE_RE.findall(query) if len(tok) >= 6]
        min_matched_terms = 2 if len(q_counts) >= 6 else 1
        scored: list[tuple[float, dict[str, Any]]] = []
        for idx, chunk in enumerate(self.chunks):
            tf_map = self._doc_freqs[idx]
            if required_identifiers and not all(tf_map.get(ident, 0) > 0 for ident in required_identifiers):
                continue
            dl = self._doc_lengths[idx] or 1
            score = 0.0
            matched_terms = 0
            for term, q_weight in q_counts.items():
                tf = tf_map.get(term, 0)
                if tf <= 0:
                    continue
                matched_terms += 1
                idf = self._idf.get(term, 0.0)
                denom = tf + self.k1 * (1.0 - self.b + self.b * (dl / self._avgdl))
                score += q_weight * idf * ((tf * (self.k1 + 1.0)) / denom)
            if score > 0.0 and matched_terms >= min_matched_terms:
                scored.append((score, dict(chunk)))
        scored.sort(key=lambda item: (-item[0], str(item[1].get("chunk_id", ""))))
        return scored
