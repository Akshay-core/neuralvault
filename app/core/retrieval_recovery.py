# Akshay-core
__author__ = "Akshay-core"

import re
from collections import Counter

from app.core.context_optimizer import grounding_confidence
from app.core.reranker import rerank
from app.core.retriever import retrieve
from app.core.response_synthesis import prioritize_chunks


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{3,}")
_STOPWORDS = {
    "about", "above", "after", "again", "also", "answer", "because", "before",
    "could", "does", "from", "give", "have", "into", "need", "show", "tell",
    "that", "their", "there", "these", "this", "what", "when", "where", "which",
    "with", "would", "your",
}


def _keywords(query: str, limit: int = 8) -> list[str]:
    counts = Counter(t.lower() for t in _TOKEN_RE.findall(query or ""))
    return [term for term, _ in counts.most_common(limit) if term not in _STOPWORDS]


def broaden_query(query: str) -> str:
    terms = _keywords(query)
    if not terms:
        return query
    return " ".join(terms)


def recover_retrieval(
    query: str,
    user_id: str,
    ranked: list[dict],
    history: list[dict],
    plan,
    workspace_id: str = "core",
) -> tuple[list[dict], dict]:
    confidence = grounding_confidence(ranked)
    if confidence.get("level") != "low" and ranked:
        return ranked, {"retry_count": 0, "strategy": "none", "confidence": confidence}

    retry_query = broaden_query(query)
    retry_top_k = max(plan.retrieval_k * 3, 12)
    retry_chunks = retrieve(
        retry_query,
        user_id=user_id,
        top_k=retry_top_k,
        workspace_id=workspace_id,
    ) if plan.needs_retrieval else []
    retry_ranked = rerank(query, retry_chunks, top_k=plan.retrieval_k) if retry_chunks else []
    retry_ranked = prioritize_chunks(query, retry_ranked, history, plan)

    if not retry_ranked:
        return ranked, {"retry_count": 1, "strategy": "broadened_keyword_retry", "confidence": confidence}

    retry_confidence = grounding_confidence(retry_ranked)
    if retry_confidence.get("score", 0) > confidence.get("score", 0):
        return retry_ranked, {
            "retry_count": 1,
            "strategy": "broadened_keyword_retry",
            "confidence": retry_confidence,
        }

    return ranked, {"retry_count": 1, "strategy": "kept_original_after_retry", "confidence": confidence}
