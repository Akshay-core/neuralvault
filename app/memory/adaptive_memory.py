# Akshay-core
__author__ = "Akshay-core"

import hashlib
import json
import re
from datetime import datetime, timedelta

from app.database.sqlite_db import get_conn
from app.memory.session_memory import storage_user_id


def cache_key(user_id: str, workspace_id: str, query: str, top_k: int) -> str:
    raw = f"{storage_user_id(user_id)}:{workspace_id or 'core'}:{top_k}:{query.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_cached_retrieval(key: str) -> list | None:
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT payload FROM retrieval_cache WHERE cache_key = ? AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)",
                (key,),
            ).fetchone()
        if not row:
            return None
        return json.loads(row["payload"])
    except Exception:
        return None


def set_cached_retrieval(user_id: str, workspace_id: str, key: str, query: str, value: list, ttl_minutes: int = 25) -> None:
    db_user = storage_user_id(user_id)
    expires = (datetime.utcnow() + timedelta(minutes=ttl_minutes)).isoformat(timespec="seconds")
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO retrieval_cache
                   (cache_key, user_id, query, payload, expires_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, db_user, query[:500], json.dumps(value, ensure_ascii=False), expires),
            )
    except Exception:
        pass


def clear_retrieval_cache(user_id: str, workspace_id: str = "") -> None:
    db_user = storage_user_id(user_id)
    workspace_clause = "AND query IS NOT NULL" if not workspace_id else "AND query IS NOT NULL"
    try:
        with get_conn() as conn:
            if workspace_id:
                conn.execute(
                    "DELETE FROM retrieval_cache WHERE user_id = ? AND cache_key LIKE ?",
                    (db_user, "%"),
                )
            else:
                conn.execute("DELETE FROM retrieval_cache WHERE user_id = ?", (db_user,))
    except Exception:
        pass


MEMORY_LAYERS = ("episodic", "semantic", "preference", "conflict")
_CONFLICT_RE = re.compile(r"\b(no|not|never|avoid|dislike|don't|do not|instead|prefer|always|must)\b", re.I)


def _memory_layer(category: str, content: str = "") -> str:
    category = (category or "general").lower()
    text = f"{category} {content}".lower()
    if category == "preference" or "prefer" in text or "style" in text:
        return "preference"
    if category in {"event", "session", "episodic"}:
        return "episodic"
    if category in {"conflict", "correction"} or "wrong" in text or "contradict" in text:
        return "conflict"
    return "semantic"


def _decay_score(memory: dict) -> float:
    if memory.get("pinned"):
        return 1.0
    try:
        raw = memory.get("updated_at") or memory.get("created_at")
        updated = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        age_days = max(0, (datetime.utcnow() - updated.replace(tzinfo=None)).days)
    except Exception:
        age_days = 0
    importance = min(max(int(memory.get("importance") or 3), 1), 5) / 5
    age_decay = max(0.22, 1 - (age_days / 180))
    return round(max(0.05, (age_decay * 0.72) + (importance * 0.28)), 4)


def _conflict_signature(title: str, content: str) -> str:
    terms = sorted(_memory_terms(f"{title} {content}"))
    anchors = [t for t in terms if len(t) >= 4][:8]
    raw = " ".join(anchors) or f"{title} {content}".lower()[:80]
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _find_conflicting_memories(conn, db_user: str, workspace_id: str, title: str, content: str, layer: str) -> list[dict]:
    if layer not in {"preference", "semantic", "conflict"}:
        return []
    new_terms = _memory_terms(f"{title} {content}")
    if not new_terms:
        return []
    rows = conn.execute(
        """SELECT * FROM saved_memories
           WHERE user_id = ? AND workspace_id = ? AND layer IN ('preference', 'semantic', 'conflict')
             AND status IN ('active', 'conflict')""",
        (db_user, workspace_id or "core"),
    ).fetchall()
    conflicts = []
    new_negative = bool(_CONFLICT_RE.search(content or ""))
    for row in rows:
        memory = dict(row)
        old_terms = _memory_terms(f"{memory.get('title', '')} {memory.get('content', '')}")
        overlap = len(new_terms & old_terms) / max(len(new_terms | old_terms), 1)
        old_negative = bool(_CONFLICT_RE.search(memory.get("content", "")))
        if overlap >= 0.34 and old_negative != new_negative:
            conflicts.append(memory)
    return conflicts


def retrieve_relevant_memories(user_id: str, query: str, workspace_id: str = "core", limit: int = 5) -> list[dict]:
    memories = list_memories(user_id, workspace_id=workspace_id)
    if not memories:
        return []
    q_terms = _memory_terms(query)
    scored = []
    for memory in memories:
        haystack = " ".join([memory.get("title", ""), memory.get("content", ""), memory.get("category", "")])
        terms = _memory_terms(haystack)
        overlap = len(q_terms & terms) / max(len(q_terms), 1) if q_terms else 0
        score = (
            overlap * 0.62
            + min(int(memory.get("importance") or 0), 5) / 5 * 0.24
            + (0.14 if memory.get("pinned") else 0)
            + float(memory.get("decay_score") or 1) * 0.12
        )
        if memory.get("status") == "conflict":
            score *= 0.45
        if score > 0.12 or memory.get("pinned"):
            item = dict(memory)
            item["relevance"] = round(score, 4)
            scored.append(item)
    scored.sort(key=lambda item: item["relevance"], reverse=True)
    return scored[:limit]


def format_memory_context(memories: list[dict]) -> str:
    if not memories:
        return ""
    lines = ["Relevant long-term user memory:"]
    for memory in memories:
        lines.append(
            f"- {memory.get('title', 'Memory')} [{memory.get('layer', 'semantic')}/{memory.get('category', 'general')}, "
            f"status {memory.get('status', 'active')}, importance {memory.get('importance', 0)}, "
            f"relevance {memory.get('relevance', 0)}]: "
            f"{memory.get('content', '')[:700]}"
        )
    return "\n".join(lines)


def _memory_terms(text: str) -> set[str]:
    import re

    stop = {
        "about", "after", "again", "also", "because", "before", "could",
        "from", "have", "into", "more", "that", "their", "there", "these",
        "this", "what", "when", "where", "which", "with", "would", "your",
    }
    return {t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", text or "") if t.lower() not in stop}


def save_feedback(user_id: str, workspace_id: str, conversation_id: str, query: str, answer: str, rating: int, notes: str = "", sources: list = None) -> bool:
    db_user = storage_user_id(user_id)
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO response_feedback
                   (user_id, workspace_id, conversation_id, query, answer, rating, notes, sources)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    db_user,
                    workspace_id or "core",
                    conversation_id or "",
                    query[:1000],
                    answer[:4000],
                    int(rating),
                    notes[:1000],
                    json.dumps(sources or [], ensure_ascii=False),
                ),
            )
        return True
    except Exception:
        return False


def feedback_summary(user_id: str, workspace_id: str = "") -> dict:
    db_user = storage_user_id(user_id)
    workspace_clause = "AND workspace_id = ?" if workspace_id else ""
    params = (db_user, workspace_id) if workspace_id else (db_user,)
    try:
        with get_conn() as conn:
            rows = conn.execute(
                f"""SELECT rating, notes, query, created_at FROM response_feedback
                    WHERE user_id = ? {workspace_clause}
                    ORDER BY created_at DESC LIMIT 80""",
                params,
            ).fetchall()
    except Exception:
        return {"count": 0, "avg_rating": 0, "recent": []}
    ratings = [int(r["rating"]) for r in rows if int(r["rating"])]
    return {
        "count": len(rows),
        "avg_rating": round(sum(ratings) / max(len(ratings), 1), 2) if ratings else 0,
        "recent": [dict(r) for r in rows[:8]],
    }


def add_memory(user_id: str, workspace_id: str, title: str, content: str, category: str = "general", importance: int = 3, pinned: bool = False) -> bool:
    db_user = storage_user_id(user_id)
    layer = _memory_layer(category, content)
    workspace = workspace_id or "core"
    try:
        with get_conn() as conn:
            conflicts = _find_conflicting_memories(conn, db_user, workspace, title, content, layer)
            conflict_group = _conflict_signature(title, content) if conflicts else ""
            status = "conflict" if conflicts else "active"
            conn.execute(
                """INSERT INTO saved_memories
                   (user_id, workspace_id, title, content, category, layer, status,
                    conflict_group, decay_score, importance, pinned)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    db_user,
                    workspace,
                    title[:120],
                    content[:4000],
                    category[:40],
                    layer,
                    status,
                    conflict_group,
                    1.0,
                    int(importance),
                    1 if pinned else 0,
                ),
            )
            if conflicts:
                row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
                memory_ids = [row["id"], *[m["id"] for m in conflicts]]
                conn.execute(
                    """UPDATE saved_memories
                       SET status = 'conflict', conflict_group = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE user_id = ? AND id IN ({})""".format(",".join("?" for _ in memory_ids)),
                    (conflict_group, db_user, *memory_ids),
                )
                conn.execute(
                    """INSERT INTO memory_conflicts
                       (user_id, workspace_id, conflict_group, memory_ids, status, reason)
                       VALUES (?, ?, ?, ?, 'open', ?)""",
                    (
                        db_user,
                        workspace,
                        conflict_group,
                        json.dumps(memory_ids),
                        "Potential contradictory preference/fact detected; resolve, merge, or let weaker memory decay.",
                    ),
                )
        return True
    except Exception:
        return False


def list_memories(user_id: str, workspace_id: str = "") -> list[dict]:
    db_user = storage_user_id(user_id)
    workspace_clause = "AND workspace_id = ?" if workspace_id else ""
    params = (db_user, workspace_id) if workspace_id else (db_user,)
    try:
        with get_conn() as conn:
            rows = conn.execute(
                f"""SELECT * FROM saved_memories
                    WHERE user_id = ? {workspace_clause}
                    ORDER BY pinned DESC, status = 'conflict' DESC, layer, importance DESC, updated_at DESC""",
                params,
            ).fetchall()
        memories = []
        with get_conn() as write_conn:
            for row in rows:
                item = dict(row)
                score = _decay_score(item)
                item["decay_score"] = score
                memories.append(item)
                write_conn.execute(
                    "UPDATE saved_memories SET decay_score = ? WHERE user_id = ? AND id = ?",
                    (score, db_user, item["id"]),
                )
        return memories
    except Exception:
        return []


def list_memory_conflicts(user_id: str, workspace_id: str = "") -> list[dict]:
    db_user = storage_user_id(user_id)
    workspace_clause = "AND workspace_id = ?" if workspace_id else ""
    params = (db_user, workspace_id) if workspace_id else (db_user,)
    try:
        with get_conn() as conn:
            rows = conn.execute(
                f"""SELECT * FROM memory_conflicts
                    WHERE user_id = ? {workspace_clause}
                    ORDER BY status = 'open' DESC, created_at DESC LIMIT 40""",
                params,
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def delete_memory(user_id: str, memory_id: int) -> bool:
    db_user = storage_user_id(user_id)
    try:
        with get_conn() as conn:
            conn.execute("DELETE FROM saved_memories WHERE user_id = ? AND id = ?", (db_user, memory_id))
        return True
    except Exception:
        return False
