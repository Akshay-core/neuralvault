# FILE: app/database/sqlite_db.py
# Akshay-core
__author__ = "Akshay-core"

import sqlite3
import os
import tempfile
from pathlib import Path
from contextlib import contextmanager
from app.ownership import AKX_BUILD_SIGNATURE, OWNER_NAME, build_fingerprint

DB_PATH = os.getenv("SQLITE_DB_PATH", "data/user_data/brain.db")


def _db_path(db_path: str) -> str:
    if os.name == "nt" and str(db_path).replace("\\", "/").startswith("/tmp/"):
        return str(Path(tempfile.gettempdir()) / str(db_path).replace("\\", "/").split("/tmp/", 1)[1])
    return str(db_path)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

def init_db(db_path: str = DB_PATH):
    db_path = _db_path(db_path)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            settings TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            workspace_id TEXT DEFAULT 'default',
            title TEXT NOT NULL DEFAULT 'New chat',
            summary TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            archived INTEGER DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            workspace_id TEXT DEFAULT 'default',
            filename TEXT,
            file_hash TEXT UNIQUE,
            file_type TEXT,
            chunk_count INTEGER DEFAULT 0,
            build_signature TEXT DEFAULT '',
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS document_profiles (
            document_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            workspace_id TEXT DEFAULT 'default',
            filename TEXT NOT NULL,
            topic_profile TEXT DEFAULT '',
            semantic_summary TEXT DEFAULT '',
            structure_map TEXT DEFAULT '',
            keyword_map TEXT DEFAULT '',
            importance_score REAL DEFAULT 0,
            source_confidence REAL DEFAULT 0,
            question_count INTEGER DEFAULT 0,
            page_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS document_chunks (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            workspace_id TEXT DEFAULT 'default',
            document_hash TEXT NOT NULL,
            filename TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            token_estimate INTEGER DEFAULT 0,
            text_hash TEXT NOT NULL,
            build_signature TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS knowledge_nodes (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            workspace_id TEXT DEFAULT 'default',
            label TEXT NOT NULL,
            node_type TEXT DEFAULT 'concept',
            domain TEXT DEFAULT '',
            summary TEXT DEFAULT '',
            importance REAL DEFAULT 0,
            evidence_count INTEGER DEFAULT 0,
            confidence REAL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS knowledge_edges (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            workspace_id TEXT DEFAULT 'default',
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation TEXT DEFAULT 'related_to',
            weight REAL DEFAULT 0,
            evidence_count INTEGER DEFAULT 0,
            confidence REAL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS concept_mentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            workspace_id TEXT DEFAULT 'default',
            node_id TEXT NOT NULL,
            document_hash TEXT NOT NULL,
            chunk_id TEXT DEFAULT '',
            filename TEXT DEFAULT '',
            mention_count INTEGER DEFAULT 1,
            evidence_preview TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS document_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            workspace_id TEXT DEFAULT 'default',
            left_document_hash TEXT NOT NULL,
            right_document_hash TEXT NOT NULL,
            relation TEXT DEFAULT 'shared_concepts',
            shared_concepts TEXT DEFAULT '[]',
            weight REAL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS knowledge_clusters (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            workspace_id TEXT DEFAULT 'default',
            label TEXT NOT NULL,
            node_ids TEXT DEFAULT '[]',
            centroid_terms TEXT DEFAULT '[]',
            weight REAL DEFAULT 0,
            confidence REAL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS topic_frequency (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            workspace_id TEXT DEFAULT 'default',
            topic TEXT NOT NULL,
            document_hash TEXT DEFAULT '',
            mention_count INTEGER DEFAULT 0,
            weight REAL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, workspace_id, topic, document_hash)
        );

        CREATE TABLE IF NOT EXISTS claim_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            workspace_id TEXT DEFAULT 'default',
            claim TEXT NOT NULL,
            support_score REAL DEFAULT 0,
            supporting_chunks TEXT DEFAULT '[]',
            confidence TEXT DEFAULT 'low',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS claim_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            workspace_id TEXT DEFAULT 'default',
            query TEXT NOT NULL,
            claim TEXT NOT NULL,
            support_score REAL DEFAULT 0,
            contradiction_score REAL DEFAULT 0,
            source_agreement REAL DEFAULT 0,
            supporting_chunks TEXT DEFAULT '[]',
            unsupported INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            model_used TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS query_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            workspace_id TEXT DEFAULT 'default',
            query TEXT,
            response_time_ms INTEGER,
            model_used TEXT,
            flagged INTEGER DEFAULT 0,
            retrieval_count INTEGER DEFAULT 0,
            cache_hit INTEGER DEFAULT 0,
            retrieval_ms INTEGER DEFAULT 0,
            rerank_ms INTEGER DEFAULT 0,
            compression_ms INTEGER DEFAULT 0,
            grounding_score REAL DEFAULT 0,
            validation_unsupported REAL DEFAULT 0,
            refined INTEGER DEFAULT 0,
            retry_count INTEGER DEFAULT 0,
            synthesis_ms INTEGER DEFAULT 0,
            generation_ms INTEGER DEFAULT 0,
            token_count INTEGER DEFAULT 0,
            token_per_second REAL DEFAULT 0,
            build_signature TEXT DEFAULT '',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS response_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            workspace_id TEXT DEFAULT 'default',
            conversation_id TEXT DEFAULT '',
            query TEXT NOT NULL,
            answer TEXT DEFAULT '',
            rating INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            sources TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS saved_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            workspace_id TEXT DEFAULT 'default',
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            layer TEXT DEFAULT 'semantic',
            status TEXT DEFAULT 'active',
            conflict_group TEXT DEFAULT '',
            decay_score REAL DEFAULT 1,
            last_accessed_at TIMESTAMP,
            importance INTEGER DEFAULT 3,
            pinned INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS memory_conflicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            workspace_id TEXT DEFAULT 'default',
            conflict_group TEXT NOT NULL,
            memory_ids TEXT DEFAULT '[]',
            status TEXT DEFAULT 'open',
            reason TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            key_hash TEXT NOT NULL UNIQUE,
            scopes TEXT DEFAULT 'read',
            rate_limit_per_min INTEGER DEFAULT 30,
            sandbox INTEGER DEFAULT 1,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS memory_vault (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            content_encrypted TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS workspaces (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            mode_hint TEXT DEFAULT '',
            color TEXT DEFAULT '#66a6ff',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            archived INTEGER DEFAULT 0,
            build_signature TEXT DEFAULT '',
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS retrieval_cache (
            cache_key TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            query TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS embedding_cache (
            text_hash TEXT PRIMARY KEY,
            model_name TEXT NOT NULL,
            vector BLOB NOT NULL,
            dim INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS vector_index_state (
            user_id INTEGER NOT NULL,
            workspace_id TEXT DEFAULT 'core',
            index_path TEXT NOT NULL,
            metadata_path TEXT NOT NULL,
            chunk_count INTEGER DEFAULT 0,
            metadata_count INTEGER DEFAULT 0,
            vector_count INTEGER DEFAULT 0,
            content_fingerprint TEXT DEFAULT '',
            status TEXT DEFAULT 'unknown',
            last_rebuilt_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, workspace_id)
        );

        CREATE TABLE IF NOT EXISTS ingestion_jobs (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            workspace_id TEXT DEFAULT 'core',
            filename TEXT NOT NULL,
            file_hash TEXT DEFAULT '',
            status TEXT NOT NULL,
            error TEXT DEFAULT '',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS system_audit_reports (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            workspace_id TEXT DEFAULT '',
            severity TEXT NOT NULL,
            summary TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_user_expiry ON sessions(user_id, expires_at);
        CREATE INDEX IF NOT EXISTS idx_documents_user_hash ON documents(user_id, file_hash);
        CREATE INDEX IF NOT EXISTS idx_chunks_user_doc ON document_chunks(user_id, document_hash, chunk_index);
        CREATE INDEX IF NOT EXISTS idx_chunks_user_hash ON document_chunks(user_id, text_hash);
        CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_user_workspace ON knowledge_nodes(user_id, workspace_id, importance);
        CREATE INDEX IF NOT EXISTS idx_knowledge_edges_user_workspace ON knowledge_edges(user_id, workspace_id, weight);
        CREATE INDEX IF NOT EXISTS idx_concept_mentions_node ON concept_mentions(user_id, workspace_id, node_id);
        CREATE INDEX IF NOT EXISTS idx_concept_mentions_doc ON concept_mentions(user_id, workspace_id, document_hash);
        CREATE INDEX IF NOT EXISTS idx_document_relations_workspace ON document_relations(user_id, workspace_id, weight);
        CREATE INDEX IF NOT EXISTS idx_knowledge_clusters_workspace ON knowledge_clusters(user_id, workspace_id, weight);
        CREATE INDEX IF NOT EXISTS idx_topic_frequency_workspace ON topic_frequency(user_id, workspace_id, topic, weight);
        CREATE INDEX IF NOT EXISTS idx_claim_index_workspace ON claim_index(user_id, workspace_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_claim_evidence_workspace ON claim_evidence(user_id, workspace_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_profiles_user_workspace ON document_profiles(user_id, workspace_id, updated_at);
        CREATE INDEX IF NOT EXISTS idx_feedback_user_workspace ON response_feedback(user_id, workspace_id, created_at);
        -- saved_memories indexes are created after ensuring schema migrations
        CREATE INDEX IF NOT EXISTS idx_memory_conflicts_workspace ON memory_conflicts(user_id, workspace_id, status, created_at);
        CREATE INDEX IF NOT EXISTS idx_query_logs_user_time ON query_logs(user_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_cache_user_expiry ON retrieval_cache(user_id, expires_at);
        CREATE INDEX IF NOT EXISTS idx_workspaces_user ON workspaces(user_id, archived, updated_at);
        CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_user_workspace ON ingestion_jobs(user_id, workspace_id, started_at);
        CREATE INDEX IF NOT EXISTS idx_audit_reports_created ON system_audit_reports(created_at, severity);
    """)
    _ensure_column(conn, "chat_history", "conversation_id", "conversation_id TEXT")
    _ensure_column(conn, "conversations", "workspace_id", "workspace_id TEXT DEFAULT 'default'")
    _ensure_column(conn, "query_logs", "retrieval_count", "retrieval_count INTEGER DEFAULT 0")
    _ensure_column(conn, "query_logs", "cache_hit", "cache_hit INTEGER DEFAULT 0")
    _ensure_column(conn, "query_logs", "retrieval_ms", "retrieval_ms INTEGER DEFAULT 0")
    _ensure_column(conn, "query_logs", "rerank_ms", "rerank_ms INTEGER DEFAULT 0")
    _ensure_column(conn, "query_logs", "compression_ms", "compression_ms INTEGER DEFAULT 0")
    _ensure_column(conn, "query_logs", "grounding_score", "grounding_score REAL DEFAULT 0")
    _ensure_column(conn, "query_logs", "validation_unsupported", "validation_unsupported REAL DEFAULT 0")
    _ensure_column(conn, "query_logs", "refined", "refined INTEGER DEFAULT 0")
    _ensure_column(conn, "query_logs", "retry_count", "retry_count INTEGER DEFAULT 0")
    _ensure_column(conn, "query_logs", "synthesis_ms", "synthesis_ms INTEGER DEFAULT 0")
    _ensure_column(conn, "query_logs", "generation_ms", "generation_ms INTEGER DEFAULT 0")
    _ensure_column(conn, "query_logs", "token_count", "token_count INTEGER DEFAULT 0")
    _ensure_column(conn, "query_logs", "token_per_second", "token_per_second REAL DEFAULT 0")
    _ensure_column(conn, "query_logs", "build_signature", "build_signature TEXT DEFAULT ''")
    _ensure_column(conn, "query_logs", "workspace_id", "workspace_id TEXT DEFAULT 'default'")
    _ensure_column(conn, "documents", "build_signature", "build_signature TEXT DEFAULT ''")
    _ensure_column(conn, "documents", "workspace_id", "workspace_id TEXT DEFAULT 'default'")
    _ensure_column(conn, "document_chunks", "build_signature", "build_signature TEXT DEFAULT ''")
    _ensure_column(conn, "document_chunks", "workspace_id", "workspace_id TEXT DEFAULT 'default'")
    _ensure_column(conn, "conversations", "pinned", "pinned INTEGER DEFAULT 0")
    _ensure_column(conn, "saved_memories", "layer", "layer TEXT DEFAULT 'semantic'")
    _ensure_column(conn, "saved_memories", "status", "status TEXT DEFAULT 'active'")
    _ensure_column(conn, "saved_memories", "conflict_group", "conflict_group TEXT DEFAULT ''")
    _ensure_column(conn, "saved_memories", "decay_score", "decay_score REAL DEFAULT 1")
    _ensure_column(conn, "saved_memories", "last_accessed_at", "last_accessed_at TIMESTAMP")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_user_convo_time ON chat_history(user_id, conversation_id, timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_workspace ON documents(user_id, workspace_id, ingested_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_workspace ON document_chunks(user_id, workspace_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_query_logs_workspace ON query_logs(user_id, workspace_id, timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_saved_memories_layer ON saved_memories(user_id, workspace_id, layer, status, decay_score)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_saved_memories_user_workspace ON saved_memories(user_id, workspace_id, pinned, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_conflicts_workspace ON memory_conflicts(user_id, workspace_id, status, created_at)")
    conn.execute(
        """INSERT OR REPLACE INTO schema_meta (key, value, updated_at)
           VALUES ('owner', ?, CURRENT_TIMESTAMP)""",
        (OWNER_NAME,),
    )
    conn.execute(
        """INSERT OR REPLACE INTO schema_meta (key, value, updated_at)
           VALUES ('build_signature', ?, CURRENT_TIMESTAMP)""",
        (AKX_BUILD_SIGNATURE,),
    )
    conn.execute(
        """INSERT OR REPLACE INTO schema_meta (key, value, updated_at)
           VALUES ('build_fingerprint', ?, CURRENT_TIMESTAMP)""",
        (build_fingerprint(),),
    )
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value, updated_at) VALUES ('schema_version', '6', CURRENT_TIMESTAMP)"
    )
    conn.commit()
    conn.close()

@contextmanager
def get_conn(db_path: str = DB_PATH):
    db_path = _db_path(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
