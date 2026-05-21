# Akshay-core
__author__ = "Akshay-core"

import json
import math
import re
from collections import Counter, defaultdict
from typing import Iterable

from app.database.sqlite_db import get_conn
from app.memory.session_memory import storage_user_id

_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_QUESTION_RE = re.compile(r"(\?|(?:^|\n)\s*(?:Q\.?\s*)?\d{1,4}[\).:-])")
_HEADING_RE = re.compile(r"^(?:[A-Z][A-Za-z0-9 /&,-]{3,80}|[0-9]+\.?\s+[A-Z][A-Za-z0-9 /&,-]{3,80})$")
_STOPWORDS = {
    "about", "after", "again", "also", "answer", "because", "before", "between",
    "chapter", "could", "course", "different", "document", "during", "every",
    "example", "following", "from", "have", "into", "more", "most", "only",
    "other", "paper", "papers", "question", "questions", "should", "than",
    "that", "their", "there", "these", "this", "through", "using", "what",
    "when", "where", "which", "with", "would", "year",
}


def _terms(text: str) -> list[str]:
    terms = [t.lower() for t in _TERM_RE.findall(text or "")]
    return [t for t in terms if len(t) > 2 and t not in _STOPWORDS]


def _top_phrases(text: str, limit: int = 18) -> list[dict]:
    words = _terms(text)
    counts = Counter(words)
    bigrams = Counter(" ".join(pair) for pair in zip(words, words[1:]) if pair[0] != pair[1])
    items = []
    for phrase, count in bigrams.most_common(limit):
        if count > 1:
            items.append({"term": phrase, "count": count, "type": "phrase"})
    for term, count in counts.most_common(limit):
        items.append({"term": term, "count": count, "type": "term"})
    return items[:limit]


def analyze_document(text: str, filename: str, document_hash: str = "") -> dict:
    clean = " ".join((text or "").split())
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    headings = [line[:90] for line in lines if _HEADING_RE.match(line)][:24]
    keywords = _top_phrases(clean)
    question_count = len(_QUESTION_RE.findall(text or ""))
    page_count = max(1, (text or "").count("\f") + 1)
    word_count = len(clean.split())
    structure = {
        "headings": headings[:16],
        "question_count": question_count,
        "estimated_pages": page_count,
        "word_count": word_count,
    }
    top_terms = [item["term"] for item in keywords[:8]]
    topic_profile = ", ".join(top_terms) or filename
    summary_seed = clean[:900]
    summary = (
        f"{filename} appears to cover {topic_profile}. "
        f"It contains about {word_count} words, {question_count} detected question markers, "
        f"and {len(headings)} structural headings. "
        f"Opening context: {summary_seed[:420]}"
    ).strip()
    importance = min(1.0, 0.25 + math.log10(max(word_count, 10)) / 5 + min(question_count, 120) / 240)
    confidence = min(1.0, 0.35 + min(word_count, 6000) / 12000 + (0.15 if headings else 0))
    return {
        "document_hash": document_hash,
        "filename": filename,
        "topic_profile": topic_profile,
        "semantic_summary": summary[:1400],
        "structure_map": structure,
        "keyword_map": keywords,
        "importance_score": round(importance, 3),
        "source_confidence": round(confidence, 3),
        "question_count": question_count,
        "page_count": page_count,
    }


def save_document_profile(user_id: str, workspace_id: str, profile: dict) -> None:
    db_user = storage_user_id(user_id)
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO document_profiles
               (document_hash, user_id, workspace_id, filename, topic_profile, semantic_summary,
                structure_map, keyword_map, importance_score, source_confidence, question_count,
                page_count, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (
                profile["document_hash"],
                db_user,
                workspace_id or "core",
                profile["filename"],
                profile.get("topic_profile", ""),
                profile.get("semantic_summary", ""),
                json.dumps(profile.get("structure_map", {}), ensure_ascii=False),
                json.dumps(profile.get("keyword_map", []), ensure_ascii=False),
                profile.get("importance_score", 0),
                profile.get("source_confidence", 0),
                profile.get("question_count", 0),
                profile.get("page_count", 0),
            ),
        )


def list_document_profiles(user_id: str, workspace_id: str = "") -> list[dict]:
    db_user = storage_user_id(user_id)
    workspace_clause = "AND workspace_id = ?" if workspace_id else ""
    params = (db_user, workspace_id) if workspace_id else (db_user,)
    try:
        with get_conn() as conn:
            rows = conn.execute(
                f"""SELECT * FROM document_profiles
                    WHERE user_id = ? {workspace_clause}
                    ORDER BY importance_score DESC, updated_at DESC""",
                params,
            ).fetchall()
    except Exception:
        return []
    profiles = []
    for row in rows:
        item = dict(row)
        for field, fallback in (("structure_map", {}), ("keyword_map", [])):
            try:
                item[field] = json.loads(item.get(field) or "")
            except Exception:
                item[field] = fallback
        profiles.append(item)
    return profiles


def route_documents(query: str, user_id: str, workspace_id: str = "", limit: int = 5) -> list[dict]:
    q_terms = set(_terms(query))
    if not q_terms:
        return []
    routed = []
    for profile in list_document_profiles(user_id, workspace_id=workspace_id):
        haystack_terms = set(_terms(" ".join([
            profile.get("filename", ""),
            profile.get("topic_profile", ""),
            profile.get("semantic_summary", ""),
            " ".join(k.get("term", "") for k in profile.get("keyword_map", [])),
        ])))
        overlap = len(q_terms & haystack_terms)
        if not overlap:
            continue
        keyword_hits = [term for term in q_terms if term in haystack_terms]
        score = (
            (overlap / max(len(q_terms), 1)) * 0.62
            + float(profile.get("importance_score") or 0) * 0.23
            + float(profile.get("source_confidence") or 0) * 0.15
        )
        routed.append({**profile, "routing_score": round(score, 4), "keyword_hits": keyword_hits[:8]})
    routed.sort(key=lambda item: item["routing_score"], reverse=True)
    return routed[:limit]


def analyze_patterns(user_id: str, workspace_id: str = "") -> dict:
    profiles = list_document_profiles(user_id, workspace_id=workspace_id)
    if not profiles:
        return {"profiles": [], "topics": [], "repetitions": [], "predictions": [], "source_count": 0}
    topic_counts = Counter()
    doc_presence = Counter()
    question_total = 0
    for profile in profiles:
        question_total += int(profile.get("question_count") or 0)
        seen = set()
        for item in profile.get("keyword_map", [])[:24]:
            term = item.get("term", "")
            count = int(item.get("count") or 0)
            if not term:
                continue
            topic_counts[term] += count
            seen.add(term)
        doc_presence.update(seen)
    repetitions = [
        {"topic": topic, "count": count, "documents": doc_presence.get(topic, 0)}
        for topic, count in topic_counts.most_common(18)
    ]
    predictions = []
    doc_count = max(len(profiles), 1)
    for item in repetitions[:10]:
        recurrence = item["documents"] / doc_count
        weight = min(0.97, (recurrence * 0.68) + min(item["count"], 80) / 250)
        predictions.append(
            {
                "topic": item["topic"],
                "probability": round(weight, 2),
                "basis": f"Seen in {item['documents']} of {doc_count} documents with {item['count']} total mentions.",
            }
        )
    return {
        "profiles": profiles,
        "topics": [{"topic": k, "weight": v} for k, v in topic_counts.most_common(24)],
        "repetitions": repetitions,
        "predictions": predictions,
        "source_count": len(profiles),
        "question_total": question_total,
    }
