# Akshay-core
__author__ = "Akshay-core"

# FILE: app/core/retriever.py
import hashlib
import math
import re
import time
from collections import Counter
from typing import List
from app.core.document_intelligence import route_documents
from app.core.embeddings import embed_query
from app.database.sqlite_db import get_conn
from app.database.vector_store import VectorStore
from app.config import TOP_K_RETRIEVAL
from app.memory.adaptive_memory import cache_key, get_cached_retrieval, set_cached_retrieval
from app.memory.session_memory import storage_user_id


_MEM_CACHE = {}
_CACHE_TTL_SECONDS = 90
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _cache_key(user_id: str, query: str, top_k: int, workspace_id: str = "") -> str:
    raw = f"{user_id}:{workspace_id or 'core'}:{top_k}:{query.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_cached(key: str):
    item = _MEM_CACHE.get(key)
    if item and item["expires"] > time.time():
        return item["value"]
    return None


def _put_cached(key: str, value: list) -> None:
    _MEM_CACHE[key] = {"value": value, "expires": time.time() + _CACHE_TTL_SECONDS}


def _lexical_scores(query: str, chunks: List[dict]) -> dict:
    q_terms = Counter(_tokens(query))
    if not q_terms:
        return {}
    scores = {}
    avg_len = max(1.0, sum(len(_tokens(c.get("text", ""))) for c in chunks) / max(len(chunks), 1))
    doc_freq = Counter()
    chunk_terms = {}
    for idx, chunk in enumerate(chunks):
        terms = Counter(_tokens(chunk.get("text", "")))
        chunk_terms[idx] = terms
        for term in set(terms):
            doc_freq[term] += 1

    total = max(len(chunks), 1)
    for idx, terms in chunk_terms.items():
        length = max(sum(terms.values()), 1)
        score = 0.0
        for term, q_count in q_terms.items():
            tf = terms.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (total - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            denom = tf + 1.2 * (1 - 0.75 + 0.75 * length / avg_len)
            score += idf * ((tf * 2.2) / denom) * min(q_count, 2)
        if score:
            scores[chunks[idx].get("chunk_id", str(idx))] = score
    if not scores:
        return {}
    max_score = max(scores.values()) or 1.0
    return {k: v / max_score for k, v in scores.items()}


def _metadata_score(query: str, chunk: dict, routed_docs: dict = None) -> float:
    q_terms = set(_tokens(query))
    if not q_terms:
        return 0.0
    fields = " ".join(
        str(chunk.get(name, ""))
        for name in ("filename", "document_hash", "doc_id", "topic_profile", "document_summary", "chunk_index")
    )
    meta_terms = set(_tokens(fields))
    overlap = min(1.0, len(q_terms & meta_terms) / max(len(q_terms), 1)) if meta_terms else 0.0
    doc_id = chunk.get("document_hash") or chunk.get("doc_id")
    routed_bonus = (routed_docs or {}).get(doc_id, 0.0)
    return min(1.0, overlap + routed_bonus * 0.55)


def _dedupe_ranked(items: List[dict], top_k: int) -> List[dict]:
    seen_text = set()
    ranked = []
    for item in sorted(items, key=lambda x: x.get("score", 0), reverse=True):
        text_hash = item.get("text_hash") or hashlib.sha256(item.get("text", "").encode("utf-8")).hexdigest()[:16]
        if text_hash in seen_text:
            continue
        seen_text.add(text_hash)
        ranked.append(item)
        if len(ranked) >= top_k:
            break
    return ranked


def _canonical_chunk_count(user_id: str, workspace_id: str = "") -> int:
    try:
        db_user = storage_user_id(user_id)
        workspace_clause = "AND workspace_id = ?" if workspace_id else ""
        params = (db_user, workspace_id) if workspace_id else (db_user,)
        with get_conn() as conn:
            return int(
                conn.execute(
                    f"SELECT COUNT(*) AS n FROM document_chunks WHERE user_id = ? {workspace_clause}",
                    params,
                ).fetchone()["n"]
            )
    except Exception:
        return 0


def retrieve(query: str, user_id: str = "global", top_k: int = TOP_K_RETRIEVAL, workspace_id: str = "") -> List[dict]:
    key = _cache_key(user_id, query, top_k, workspace_id=workspace_id)
    cached = _get_cached(key)
    if cached is not None:
        return cached
    persistent_key = cache_key(user_id, workspace_id or "core", query, top_k)
    cached = get_cached_retrieval(persistent_key)
    if cached is not None:
        _put_cached(key, cached)
        return cached

    vs = VectorStore(user_id=user_id)
    canonical_count = _canonical_chunk_count(user_id, workspace_id=workspace_id)
    if canonical_count <= 0:
        return []
    if vs.count() != canonical_count:
        vs.rebuild_from_sqlite(workspace_id=workspace_id)
    if vs.count() == 0:
        return []

    routed = route_documents(query, user_id, workspace_id=workspace_id, limit=6)
    routed_scores = {doc["document_hash"]: doc["routing_score"] for doc in routed}
    routed_hashes = set(routed_scores)

    q_vec = embed_query(query)
    semantic = vs.search(q_vec, top_k=min(max(top_k * 4, 12), vs.count()))
    if not semantic:
        return []

    scoped_metadata = [
        meta for meta in vs.metadata
        if not workspace_id or meta.get("workspace_id") in ("", None, workspace_id)
    ]
    if routed_hashes:
        routed_metadata = [
            meta for meta in scoped_metadata
            if (meta.get("document_hash") or meta.get("doc_id")) in routed_hashes
        ]
        scoped_metadata = routed_metadata or scoped_metadata

    lexical = _lexical_scores(query, scoped_metadata)
    merged = {}
    for rank, (dist, meta) in enumerate(sorted(semantic, key=lambda x: x[0])):
        if workspace_id and meta.get("workspace_id") not in ("", None, workspace_id):
            continue
        if routed_hashes and (meta.get("document_hash") or meta.get("doc_id")) not in routed_hashes:
            # Keep a small cross-document escape hatch for broad questions.
            if rank > max(top_k, 6):
                continue
        chunk_id = meta.get("chunk_id", str(rank))
        semantic_score = max(0.0, 1.0 - (dist / 2.0))
        merged[chunk_id] = {
            **meta,
            "semantic_score": round(semantic_score, 4),
            "keyword_score": round(lexical.get(chunk_id, 0.0), 4),
            "rank_position": rank + 1,
        }

    for meta in scoped_metadata:
        chunk_id = meta.get("chunk_id")
        lex_score = lexical.get(chunk_id, 0.0)
        if lex_score <= 0:
            continue
        if chunk_id not in merged:
            merged[chunk_id] = {**meta, "semantic_score": 0.0, "rank_position": 999}
        merged[chunk_id]["keyword_score"] = round(lex_score, 4)

    results = []
    for item in merged.values():
        semantic_score = item.get("semantic_score", 0.0)
        keyword_score = item.get("keyword_score", 0.0)
        metadata_score = _metadata_score(query, item, routed_scores)
        rank_bonus = 1 / (1 + item.get("rank_position", 999))
        item["metadata_score"] = round(metadata_score, 4)
        doc_importance = float(item.get("document_importance") or 0)
        source_confidence = float(item.get("source_confidence") or 0)
        score = (
            (semantic_score * 0.56)
            + (keyword_score * 0.23)
            + (metadata_score * 0.12)
            + (rank_bonus * 0.04)
            + (doc_importance * 0.025)
            + (source_confidence * 0.025)
        )
        item["score"] = round(score, 4)
        item["confidence"] = "high" if score >= 0.62 else "medium" if score >= 0.38 else "low"
        if routed:
            item["routed_documents"] = [
                {
                    "filename": doc["filename"],
                    "routing_score": doc["routing_score"],
                    "keyword_hits": doc.get("keyword_hits", []),
                }
                for doc in routed[:3]
            ]
        results.append(item)

    ranked = _dedupe_ranked(results, top_k)
    _put_cached(key, ranked)
    set_cached_retrieval(user_id, workspace_id or "core", persistent_key, query, ranked)
    return ranked


def format_context(chunks: List[dict], token_budget: int = 1200) -> str:
    if not chunks:
        return ""
    parts = []
    used = 0
    for i, c in enumerate(chunks):
        src = c.get("filename", "unknown")
        text = c.get("text", "")
        estimate = max(1, c.get("token_estimate") or len(text.split()))
        if used + estimate > token_budget and parts:
            break
        used += estimate
        confidence = c.get("confidence", "unknown")
        score = c.get("score", 0)
        parts.append(f"[Source {i+1}: {src} | confidence={confidence} | score={score}]\n{text}")
    return "\n\n---\n\n".join(parts)
