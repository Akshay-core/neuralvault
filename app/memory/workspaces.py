# Akshay-core
__author__ = "Akshay-core"

import uuid

from app.database.sqlite_db import get_conn
from app.memory.session_memory import storage_user_id
from app.ownership import signature_label


DEFAULT_WORKSPACES = [
    ("core", "Akshay Core", "Main local AI workspace", "#66a6ff"),
    ("research", "Research", "Deep searches, documents, and evidence", "#5be49b"),
    ("study", "Study", "Notes, quizzes, summaries, and exam prep", "#ffd166"),
    ("build", "Build", "Projects, architecture, debugging, and product work", "#37d4ff"),
]


def _safe_workspace_id(value: str = "") -> str:
    text = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in str(value or "").strip().lower())
    return text[:60] or "core"


def ensure_default_workspaces(user_id: str = "global") -> None:
    db_user = storage_user_id(user_id)
    with get_conn() as conn:
        for wid, name, description, color in DEFAULT_WORKSPACES:
            conn.execute(
                """INSERT OR IGNORE INTO workspaces
                   (id, user_id, name, description, color, build_signature)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (wid, db_user, name, description, color, signature_label()),
            )


def get_or_create_workspace(user_id: str = "global", workspace_id: str = "") -> str:
    ensure_default_workspaces(user_id)
    db_user = storage_user_id(user_id)
    workspace_id = _safe_workspace_id(workspace_id or "core")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM workspaces WHERE user_id = ? AND id = ? AND archived = 0",
            (db_user, workspace_id),
        ).fetchone()
        if row:
            return row["id"]
        conn.execute(
            """INSERT INTO workspaces (id, user_id, name, description, color, build_signature)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (workspace_id, db_user, workspace_id.replace("-", " ").title(), "Local workspace", "#66a6ff", signature_label()),
        )
        return workspace_id


def create_workspace(user_id: str, name: str, description: str = "", color: str = "#66a6ff") -> str:
    ensure_default_workspaces(user_id)
    db_user = storage_user_id(user_id)
    base = _safe_workspace_id(name)
    workspace_id = base
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM workspaces WHERE user_id = ? AND id = ?", (db_user, workspace_id)).fetchone():
            workspace_id = f"{base}-{uuid.uuid4().hex[:6]}"
        conn.execute(
            """INSERT INTO workspaces (id, user_id, name, description, color, build_signature)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (workspace_id, db_user, name[:80] or "Workspace", description[:240], color, signature_label()),
        )
    return workspace_id


def list_workspaces(user_id: str = "global") -> list[dict]:
    ensure_default_workspaces(user_id)
    db_user = storage_user_id(user_id)
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT w.id, w.name, w.description, w.color, w.updated_at,
                          COUNT(DISTINCT c.id) AS chats,
                          COUNT(DISTINCT d.id) AS docs
                   FROM workspaces w
                   LEFT JOIN conversations c ON c.workspace_id = w.id AND c.user_id = w.user_id AND c.archived = 0
                   LEFT JOIN documents d ON d.workspace_id = w.id AND d.user_id = w.user_id
                   WHERE w.user_id = ? AND w.archived = 0
                   GROUP BY w.id
                   ORDER BY CASE w.id WHEN 'core' THEN 0 ELSE 1 END, w.updated_at DESC""",
                (db_user,),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def workspace_label(user_id: str, workspace_id: str) -> str:
    db_user = storage_user_id(user_id)
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT name FROM workspaces WHERE user_id = ? AND id = ?",
                (db_user, workspace_id),
            ).fetchone()
            return row["name"] if row else workspace_id
    except Exception:
        return workspace_id
