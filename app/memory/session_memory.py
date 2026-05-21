# Akshay-core
__author__ = "Akshay-core"

# FILE: app/memory/session_memory.py
import uuid
from collections import defaultdict
from typing import List
from app.database.sqlite_db import get_conn

# in-memory store for current session
_sessions: dict = defaultdict(list)
MAX_HISTORY = 20
SUMMARY_AFTER_MESSAGES = 18
SUMMARY_RECENT_KEEP = 10


def _session_key(user_id: str, conversation_id: str = "") -> str:
    return f"{user_id}:{conversation_id or 'default'}"


def _db_user_id(user_id: str) -> int:
    """Return a real users.id for FK-safe conversation storage."""
    try:
        numeric = int(user_id)
    except (TypeError, ValueError):
        numeric = None

    with get_conn() as conn:
        if numeric is not None:
            row = conn.execute("SELECT id FROM users WHERE id = ?", (numeric,)).fetchone()
            if row:
                return numeric

        username = f"local_{str(user_id or 'global')[:48]}"
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if row:
            return int(row["id"])
        conn.execute(
            "INSERT INTO users (username, password_hash, settings) VALUES (?, ?, ?)",
            (username, "local-system-user", '{"system": true}'),
        )
        return int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])


def storage_user_id(user_id: str) -> int:
    return _db_user_id(user_id)


def _conversation_summary(messages: list[dict], limit: int = 8) -> str:
    older = messages[:-SUMMARY_RECENT_KEEP]
    if not older:
        return ""
    user_points = []
    assistant_points = []
    for msg in older[-limit:]:
        content = " ".join((msg.get("content") or "").split())
        if not content:
            continue
        if msg.get("role") == "user":
            user_points.append(content[:130])
        elif msg.get("role") == "assistant":
            assistant_points.append(content[:130])
    parts = []
    if user_points:
        parts.append("Older user focus: " + " | ".join(user_points[-3:]))
    if assistant_points:
        parts.append("Earlier assistant conclusions: " + " | ".join(assistant_points[-3:]))
    return "\n".join(parts)[:1200]


def maybe_update_conversation_summary(user_id: str, conversation_id: str) -> str:
    db_user = _db_user_id(user_id)
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT role, content FROM chat_history
                   WHERE user_id = ? AND conversation_id = ?
                   ORDER BY timestamp ASC""",
                (db_user, conversation_id),
            ).fetchall()
            messages = [dict(r) for r in rows]
            if len(messages) < SUMMARY_AFTER_MESSAGES:
                return ""
            summary = _conversation_summary(messages)
            if summary:
                conn.execute(
                    "UPDATE conversations SET summary = ? WHERE id = ? AND user_id = ?",
                    (summary, conversation_id, db_user),
                )
            return summary
    except Exception:
        return ""


def get_conversation_summary(user_id: str, conversation_id: str = "") -> str:
    db_user = _db_user_id(user_id)
    conversation_id = ensure_conversation(user_id, conversation_id)
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT summary FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, db_user),
            ).fetchone()
            return (row["summary"] if row else "") or ""
    except Exception:
        return ""


def create_conversation(user_id: str, title: str = "New chat", workspace_id: str = "core") -> str:
    conversation_id = uuid.uuid4().hex
    db_user = _db_user_id(user_id)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations (id, user_id, workspace_id, title) VALUES (?, ?, ?, ?)",
            (conversation_id, db_user, workspace_id or "core", title[:80] or "New chat"),
        )
    return conversation_id


def fork_conversation(user_id: str, conversation_id: str, title: str = "Forked chat", workspace_id: str = "") -> str:
    db_user = _db_user_id(user_id)
    conversation_id = ensure_conversation(user_id, conversation_id)
    new_id = uuid.uuid4().hex
    try:
        with get_conn() as conn:
            source = conn.execute(
                "SELECT title, summary, workspace_id FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, db_user),
            ).fetchone()
            new_title = title if title != "Forked chat" else f"Fork: {(source['title'] if source else 'Chat')[:56]}"
            target_workspace = workspace_id or (source["workspace_id"] if source else "core") or "core"
            conn.execute(
                "INSERT INTO conversations (id, user_id, workspace_id, title, summary) VALUES (?, ?, ?, ?, ?)",
                (new_id, db_user, target_workspace, new_title[:80], (source["summary"] if source else "") or ""),
            )
            rows = conn.execute(
                """SELECT role, content, model_used FROM chat_history
                   WHERE user_id = ? AND conversation_id = ?
                   ORDER BY timestamp ASC""",
                (db_user, conversation_id),
            ).fetchall()
            conn.executemany(
                """INSERT INTO chat_history (conversation_id, user_id, role, content, model_used)
                   VALUES (?, ?, ?, ?, ?)""",
                [(new_id, db_user, r["role"], r["content"], r["model_used"]) for r in rows],
            )
        load_history_from_db(user_id, conversation_id=new_id)
    except Exception:
        pass
    return new_id


def ensure_conversation(user_id: str, conversation_id: str = "", workspace_id: str = "core") -> str:
    db_user = _db_user_id(user_id)
    if conversation_id:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, db_user),
            ).fetchone()
        if row:
            return conversation_id
    return get_or_create_default_conversation(user_id, workspace_id=workspace_id)


def get_or_create_default_conversation(user_id: str, workspace_id: str = "core") -> str:
    db_user = _db_user_id(user_id)
    workspace_id = workspace_id or "core"
    with get_conn() as conn:
        row = conn.execute(
            """SELECT id FROM conversations
               WHERE user_id = ? AND workspace_id = ? AND archived = 0
               ORDER BY updated_at DESC LIMIT 1""",
            (db_user, workspace_id),
        ).fetchone()
        if row:
            return row["id"]
        conversation_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO conversations (id, user_id, workspace_id, title) VALUES (?, ?, ?, ?)",
            (conversation_id, db_user, workspace_id, "New chat"),
        )
        return conversation_id


def list_conversations(user_id: str, limit: int = 50, workspace_id: str = "") -> List[dict]:
    db_user = _db_user_id(user_id)
    try:
        with get_conn() as conn:
            workspace_clause = "AND c.workspace_id = ?" if workspace_id else ""
            params = (db_user, workspace_id, limit) if workspace_id else (db_user, limit)
            rows = conn.execute(
                f"""SELECT c.id, c.title, c.summary, c.workspace_id, c.updated_at,
                          COALESCE(c.pinned, 0) AS pinned,
                          COUNT(h.id) AS message_count
                   FROM conversations c
                   LEFT JOIN chat_history h ON h.conversation_id = c.id
                   WHERE c.user_id = ? AND c.archived = 0 {workspace_clause}
                   GROUP BY c.id
                   ORDER BY pinned DESC, c.updated_at DESC LIMIT ?""",
                params,
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def add_message(user_id: str, role: str, content: str, model: str = "", conversation_id: str = ""):
    conversation_id = ensure_conversation(user_id, conversation_id)
    db_user = _db_user_id(user_id)
    key = _session_key(user_id, conversation_id)
    _sessions[key].append({"role": role, "content": content})
    if len(_sessions[key]) > MAX_HISTORY * 2:
        _sessions[key] = _sessions[key][-MAX_HISTORY * 2:]
    # persist to DB
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO chat_history (conversation_id, user_id, role, content, model_used)
                   VALUES (?,?,?,?,?)""",
                (conversation_id, db_user, role, content, model)
            )
            title = content.strip().replace("\n", " ")[:64]
            if role == "user" and title:
                conn.execute(
                    """UPDATE conversations
                       SET title = CASE WHEN title = 'New chat' THEN ? ELSE title END,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND user_id = ?""",
                    (title, conversation_id, db_user),
                )
            else:
                conn.execute(
                    "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                    (conversation_id, db_user),
                )
        if role == "assistant":
            maybe_update_conversation_summary(user_id, conversation_id)
    except Exception:
        pass


def get_history(user_id: str, conversation_id: str = "") -> List[dict]:
    conversation_id = ensure_conversation(user_id, conversation_id)
    key = _session_key(user_id, conversation_id)
    if key not in _sessions:
        load_history_from_db(user_id, conversation_id=conversation_id)
    return list(_sessions.get(key, []))


def clear_session(user_id: str, conversation_id: str = ""):
    conversation_id = ensure_conversation(user_id, conversation_id)
    db_user = _db_user_id(user_id)
    _sessions[_session_key(user_id, conversation_id)] = []
    try:
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM chat_history WHERE user_id = ? AND conversation_id = ?",
                (db_user, conversation_id),
            )
    except Exception:
        pass


def delete_conversation(user_id: str, conversation_id: str) -> bool:
    db_user = _db_user_id(user_id)
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE conversations SET archived = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                (conversation_id, db_user),
            )
            conn.execute(
                "DELETE FROM chat_history WHERE user_id = ? AND conversation_id = ?",
                (db_user, conversation_id),
            )
        _sessions.pop(_session_key(user_id, conversation_id), None)
        return True
    except Exception:
        return False


def set_conversation_pinned(user_id: str, conversation_id: str, pinned: bool = True) -> bool:
    db_user = _db_user_id(user_id)
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE conversations SET pinned = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                (1 if pinned else 0, conversation_id, db_user),
            )
        return True
    except Exception:
        return False


def delete_message(user_id: str, message_id: int, conversation_id: str = "") -> bool:
    db_user = _db_user_id(user_id)
    try:
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM chat_history WHERE user_id = ? AND id = ?",
                (db_user, message_id),
            )
        load_history_from_db(user_id, conversation_id=conversation_id)
        return True
    except Exception:
        return False


def get_persisted_history(user_id: str, limit: int = 200, conversation_id: str = "") -> List[dict]:
    conversation_id = ensure_conversation(user_id, conversation_id)
    db_user = _db_user_id(user_id)
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT id, role, content, model_used, timestamp FROM chat_history
                   WHERE user_id = ? AND conversation_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (db_user, conversation_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]
    except Exception:
        return []


def load_history_from_db(user_id: str, limit: int = 20, conversation_id: str = "") -> List[dict]:
    conversation_id = ensure_conversation(user_id, conversation_id)
    db_user = _db_user_id(user_id)
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT role, content FROM chat_history
                   WHERE user_id = ? AND conversation_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (db_user, conversation_id, limit)
            ).fetchall()
            msgs = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
            _sessions[_session_key(user_id, conversation_id)] = msgs
            return msgs
    except Exception:
        return []
