# Akshay-core
__author__ = "Akshay-core"

import re
from collections import Counter, defaultdict

from app.database.sqlite_db import get_conn
from app.memory.session_memory import storage_user_id


_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,}")
_STOPWORDS = {
    "about", "again", "answer", "assistant", "because", "before", "being",
    "could", "document", "documents", "from", "have", "into", "local",
    "make", "more", "need", "should", "that", "their", "there", "these",
    "this", "using", "what", "when", "where", "which", "with", "would",
}


def _terms(text: str) -> list[str]:
    terms = [t.lower() for t in _TERM_RE.findall(text or "")]
    return [t for t in terms if t not in _STOPWORDS]


def build_memory_graph(user_id: str = "global", limit: int = 320, workspace_id: str = "") -> dict:
    db_user = storage_user_id(user_id)
    workspace_clause = "AND workspace_id = ?" if workspace_id else ""
    workspace_params = (workspace_id,) if workspace_id else ()
    try:
        with get_conn() as conn:
            chat_rows = conn.execute(
                f"""SELECT h.content FROM chat_history h
                   LEFT JOIN conversations c ON c.id = h.conversation_id
                   WHERE h.user_id = ? {('AND c.workspace_id = ?' if workspace_id else '')}
                   ORDER BY timestamp DESC LIMIT ?""",
                (db_user, *workspace_params, limit),
            ).fetchall()
            doc_rows = conn.execute(
                f"""SELECT filename, text FROM document_chunks
                   WHERE user_id = ? {workspace_clause}
                   ORDER BY created_at DESC LIMIT ?""",
                (db_user, *workspace_params, limit),
            ).fetchall()
    except Exception:
        return {"topics": [], "edges": [], "source_count": 0}

    topic_counts = Counter()
    edges = Counter()
    source_count = 0
    for row in chat_rows:
        unique = list(dict.fromkeys(_terms(row["content"])[:16]))
        if not unique:
            continue
        source_count += 1
        topic_counts.update(unique)
        for left in unique[:8]:
            for right in unique[:8]:
                if left < right:
                    edges[(left, right)] += 1

    for row in doc_rows:
        unique = list(dict.fromkeys((_terms(row["filename"]) + _terms(row["text"]))[:18]))
        if not unique:
            continue
        source_count += 1
        topic_counts.update(unique)
        for left in unique[:8]:
            for right in unique[:8]:
                if left < right:
                    edges[(left, right)] += 1

    topics = [
        {"topic": topic, "weight": count}
        for topic, count in topic_counts.most_common(18)
    ]
    edge_rows = [
        {"from": left, "to": right, "weight": weight}
        for (left, right), weight in edges.most_common(28)
        if weight > 1
    ]
    return {"topics": topics, "edges": edge_rows, "source_count": source_count}


def search_everything(user_id: str, query: str, limit: int = 8, workspace_id: str = "") -> list[dict]:
    db_user = storage_user_id(user_id)
    q_terms = set(_terms(query))
    if not q_terms:
        return []

    results = []
    workspace_params = (workspace_id,) if workspace_id else ()
    try:
        with get_conn() as conn:
            chats = conn.execute(
                f"""SELECT h.role, h.content, h.timestamp FROM chat_history h
                   LEFT JOIN conversations c ON c.id = h.conversation_id
                   WHERE h.user_id = ? {('AND c.workspace_id = ?' if workspace_id else '')}
                   ORDER BY timestamp DESC LIMIT 180""",
                (db_user, *workspace_params),
            ).fetchall()
            docs = conn.execute(
                f"""SELECT filename, text, created_at FROM document_chunks
                   WHERE user_id = ? {('AND workspace_id = ?' if workspace_id else '')}
                   ORDER BY created_at DESC LIMIT 180""",
                (db_user, *workspace_params),
            ).fetchall()
    except Exception:
        return []

    for row in chats:
        content = row["content"] or ""
        overlap = len(set(_terms(content)) & q_terms)
        if overlap:
            results.append(
                {
                    "type": "chat",
                    "title": f"{row['role']} message",
                    "preview": content[:240],
                    "score": overlap,
                    "timestamp": row["timestamp"],
                }
            )

    for row in docs:
        content = row["text"] or ""
        terms = set(_terms(row["filename"]) + _terms(content))
        overlap = len(terms & q_terms)
        if overlap:
            results.append(
                {
                    "type": "document",
                    "title": row["filename"],
                    "preview": content[:240],
                    "score": overlap,
                    "timestamp": row["created_at"],
                }
            )

    results.sort(key=lambda item: (item["score"], item.get("timestamp") or ""), reverse=True)
    return results[:limit]
