# Akshay-core
__author__ = "Akshay-core"

# FILE: analytics/usage_tracker.py
from app.database.sqlite_db import get_conn
from app.memory.session_memory import storage_user_id
from app.utils.logger import get_logger

logger = get_logger("analytics")


def _scope(workspace_id: str = "") -> tuple[str, tuple]:
    if workspace_id:
        return "AND workspace_id = ?", (workspace_id,)
    return "", ()


def get_user_stats(user_id: str, workspace_id: str = "") -> dict:
    db_user = storage_user_id(user_id)
    workspace_clause, workspace_params = _scope(workspace_id)
    params = (db_user, *workspace_params)
    try:
        with get_conn() as conn:
            total_queries = conn.execute(
                f"SELECT COUNT(*) as n FROM query_logs WHERE user_id = ? {workspace_clause}",
                params,
            ).fetchone()["n"]

            avg_resp = conn.execute(
                f"SELECT AVG(response_time_ms) as avg FROM query_logs WHERE user_id = ? {workspace_clause}",
                params,
            ).fetchone()["avg"]

            doc_count = conn.execute(
                f"SELECT COUNT(*) as n FROM documents WHERE user_id = ? {workspace_clause}",
                params,
            ).fetchone()["n"]

            model_usage = conn.execute(
                f"""SELECT model_used, COUNT(*) as cnt
                   FROM query_logs WHERE user_id = ? {workspace_clause}
                   GROUP BY model_used ORDER BY cnt DESC""",
                params,
            ).fetchall()

            recent_queries = conn.execute(
                f"""SELECT query, response_time_ms, model_used, retrieval_ms, rerank_ms,
                          compression_ms, grounding_score, validation_unsupported,
                          refined, retry_count, synthesis_ms, generation_ms,
                          token_count, token_per_second, timestamp
                   FROM query_logs WHERE user_id = ? {workspace_clause}
                   ORDER BY timestamp DESC LIMIT 10""",
                params,
            ).fetchall()

            pipeline = conn.execute(
                f"""SELECT AVG(retrieval_ms) AS retrieval_ms,
                          AVG(rerank_ms) AS rerank_ms,
                          AVG(compression_ms) AS compression_ms,
                          AVG(grounding_score) AS grounding_score,
                          AVG(validation_unsupported) AS validation_unsupported,
                          AVG(refined) AS refined_rate,
                          AVG(retry_count) AS retry_rate,
                          AVG(synthesis_ms) AS synthesis_ms,
                          AVG(generation_ms) AS generation_ms,
                          AVG(token_per_second) AS token_per_second
                   FROM query_logs WHERE user_id = ? {workspace_clause}""",
                params,
            ).fetchone()

            return {
                "total_queries": total_queries,
                "avg_response_ms": round(avg_resp or 0, 1),
                "documents_uploaded": doc_count,
                "model_usage": [dict(r) for r in model_usage],
                "recent_queries": [dict(r) for r in recent_queries],
                "pipeline": dict(pipeline) if pipeline else {},
            }
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return {}


def get_global_stats() -> dict:
    try:
        with get_conn() as conn:
            users = conn.execute("SELECT COUNT(*) as n FROM users").fetchone()["n"]
            queries = conn.execute("SELECT COUNT(*) as n FROM query_logs").fetchone()["n"]
            docs = conn.execute("SELECT COUNT(*) as n FROM documents").fetchone()["n"]
            return {
                "total_users": users,
                "total_queries": queries,
                "total_documents": docs,
            }
    except Exception:
        return {}
