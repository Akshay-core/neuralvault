# Akshay-core
__author__ = "Akshay-core"

# FILE: app/core/reranker.py
import hashlib
import re
from collections import Counter
from typing import List


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")
_CACHE = {}
_cross_encoder = None
_cross_encoder_attempted = False


def _tokens(text: str) -> list:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _fallback_score(query: str, text: str) -> float:
    q = Counter(_tokens(query))
    d = Counter(_tokens(text))
    if not q or not d:
        return 0.0
    overlap = sum(min(count, d.get(term, 0)) for term, count in q.items())
    coverage = overlap / max(sum(q.values()), 1)
    density = overlap / max(sum(d.values()), 1)
    phrase_bonus = 0.12 if query.lower()[:80] in text.lower() else 0.0
    return min(1.0, (coverage * 0.72) + (density * 1.4) + phrase_bonus)


def _get_cross_encoder():
    global _cross_encoder, _cross_encoder_attempted
    if _cross_encoder is not None or _cross_encoder_attempted:
        return _cross_encoder
    _cross_encoder_attempted = True
    try:
        from sentence_transformers import CrossEncoder

        _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", local_files_only=True)
    except Exception:
        _cross_encoder = None
    return _cross_encoder


def rerank(query: str, chunks: List[dict], top_k: int) -> List[dict]:
    if not chunks:
        return []

    cache_key = hashlib.sha256(
        (query + "|" + "|".join(c.get("chunk_id", "") for c in chunks)).encode("utf-8")
    ).hexdigest()
    if cache_key in _CACHE:
        return _CACHE[cache_key][:top_k]

    model = _get_cross_encoder()
    ranked = []
    if model is not None:
        pairs = [(query, c.get("text", "")[:1200]) for c in chunks]
        try:
            scores = model.predict(pairs)
            for chunk, score in zip(chunks, scores):
                item = dict(chunk)
                rerank_score = float(score)
                item["rerank_score"] = round(rerank_score, 4)
                item["score"] = round((item.get("score", 0.0) * 0.45) + (max(0.0, min(1.0, rerank_score)) * 0.55), 4)
                ranked.append(item)
        except Exception:
            ranked = []

    if not ranked:
        for chunk in chunks:
            item = dict(chunk)
            score = _fallback_score(query, item.get("text", ""))
            item["rerank_score"] = round(score, 4)
            item["score"] = round((item.get("score", 0.0) * 0.62) + (score * 0.38), 4)
            ranked.append(item)

    ranked.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    for item in ranked:
        score = item.get("score", 0.0)
        item["confidence"] = "high" if score >= 0.62 else "medium" if score >= 0.38 else "low"
    _CACHE[cache_key] = ranked
    return ranked[:top_k]
