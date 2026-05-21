# FILE: app/ingestion/file_manager.py
# Akshay-core
__author__ = "Akshay-core"

import hashlib
import os
import unicodedata
from pathlib import Path
from typing import Optional
from app.config import RAW_DOCS_DIR, PROCESSED_DOCS_DIR
from app.ingestion.pdf_loader import extract_text_from_pdf, file_hash
from app.core.chunker import chunk_with_metadata
from app.core.document_intelligence import analyze_document, save_document_profile
from app.core.embeddings import embed_texts
from app.core.knowledge_engine import save_document_knowledge
from app.database.vector_store import VectorStore
from app.database.sqlite_db import get_conn
from app.memory.session_memory import storage_user_id
from app.memory.adaptive_memory import clear_retrieval_cache
from app.ownership import signature_label
from app.utils.logger import get_logger

logger = get_logger("file_manager")
MAX_INGEST_BYTES = 50 * 1024 * 1024

_TEXT_REPLACEMENTS = str.maketrans({
    "\u2212": "-",       # minus sign
    "\u2013": "-",       # en dash
    "\u2014": "-",       # em dash
    "\u221a": "sqrt",    # square root
    "\u2211": "sum",     # summation
    "\u222b": "integral",
    "\u03b1": "alpha",
    "\u03b2": "beta",
    "\u03b3": "gamma",
    "\u03b8": "theta",
    "\u03c0": "pi",
    "\u00d7": "x",
    "\u00f7": "/",
    "\u2264": "<=",
    "\u2265": ">=",
    "\u2260": "!=",
})


def _make_text_portable(text: str) -> str:
    """Keep ingestion robust on Windows consoles/filesystems that default to cp1252."""
    text = unicodedata.normalize("NFKC", text).translate(_TEXT_REPLACEMENTS)
    return text.encode("cp1252", errors="replace").decode("cp1252")


def ingest_file(file_path: str, user_id: str = "global", original_name: str = "", workspace_id: str = "core") -> dict:
    db_user = storage_user_id(user_id)
    workspace_id = workspace_id or "core"
    path = Path(file_path)
    if not path.exists():
        return {"success": False, "error": "File not found"}
    if path.stat().st_size > MAX_INGEST_BYTES:
        return {"success": False, "error": "File too large (max 50MB)"}

    fhash = file_hash(file_path)
    fname = original_name or path.name
    ext = path.suffix.lower()

    try:
        with get_conn() as conn:
            existing = conn.execute(
                """SELECT filename, chunk_count FROM documents
                   WHERE user_id = ? AND file_hash = ?""",
                (db_user, fhash)
            ).fetchone()
            if existing:
                return {
                    "success": True,
                    "filename": existing["filename"],
                    "chunks": existing["chunk_count"],
                    "hash": fhash,
                    "skipped": True,
                }
    except Exception as e:
        logger.warning(f"Duplicate check failed (continuing): {e}")

    # extract text
    text = None
    if ext == ".pdf":
        text = extract_text_from_pdf(file_path)
    elif ext in [".txt", ".md"]:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    else:
        return {"success": False, "error": f"Unsupported file type: {ext}"}

    if not text or len(text.strip()) < 50:
        return {"success": False, "error": "Could not extract usable text"}

    text = _make_text_portable(text)

    # save processed
    out_path = PROCESSED_DOCS_DIR / f"{fhash}.txt"
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

    profile = analyze_document(text, fname, document_hash=fhash)
    # chunk + embed
    chunks = chunk_with_metadata(text, doc_id=fhash, filename=fname)
    seen_hashes = set()
    deduped = []
    for chunk in chunks:
        if chunk["text_hash"] in seen_hashes:
            continue
        seen_hashes.add(chunk["text_hash"])
        chunk["workspace_id"] = workspace_id
        chunk["topic_profile"] = profile.get("topic_profile", "")
        chunk["document_summary"] = profile.get("semantic_summary", "")[:600]
        chunk["document_importance"] = profile.get("importance_score", 0)
        chunk["source_confidence"] = profile.get("source_confidence", 0)
        deduped.append(chunk)
    chunks = deduped
    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(texts)

    job_id = hashlib.sha256(f"{db_user}:{workspace_id}:{fhash}".encode("utf-8")).hexdigest()[:24]
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO ingestion_jobs
                   (id, user_id, workspace_id, filename, file_hash, status, error, started_at)
                   VALUES (?, ?, ?, ?, ?, 'running', '', CURRENT_TIMESTAMP)""",
                (job_id, db_user, workspace_id, fname, fhash),
            )
            conn.execute("""
                INSERT OR IGNORE INTO documents (user_id, workspace_id, filename, file_hash, file_type, chunk_count, build_signature)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (db_user, workspace_id, fname, fhash, ext, len(chunks), signature_label()))
            conn.executemany(
                """INSERT OR IGNORE INTO document_chunks
                   (id, user_id, workspace_id, document_hash, filename, chunk_index, text, token_estimate, text_hash, build_signature)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        c["chunk_id"],
                        db_user,
                        workspace_id,
                        fhash,
                        fname,
                        c["chunk_index"],
                        c["text"],
                        c.get("token_estimate", len(c["text"].split())),
                        c["text_hash"],
                        signature_label(),
                    )
                    for c in chunks
                ],
            )
            conn.execute(
                """UPDATE ingestion_jobs
                   SET status = 'sqlite_committed', finished_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (job_id,),
            )
        clear_retrieval_cache(user_id, workspace_id)
    except Exception as e:
        logger.error(f"Ingestion transaction failed for {fname}: {e}")
        try:
            with get_conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO ingestion_jobs
                       (id, user_id, workspace_id, filename, file_hash, status, error, finished_at)
                       VALUES (?, ?, ?, ?, ?, 'failed', ?, CURRENT_TIMESTAMP)""",
                    (job_id, db_user, workspace_id, fname, fhash, str(e)[:600]),
                )
        except Exception:
            logger.exception("Failed to record ingestion failure")
        return {"success": False, "error": f"Database ingestion failed: {e}"}

    try:
        save_document_profile(user_id, workspace_id, profile)
    except Exception as e:
        logger.warning(f"Document profile save failed; canonical chunks are intact: {e}")
    try:
        save_document_knowledge(user_id, workspace_id, profile, chunks)
    except Exception as e:
        logger.warning(f"Knowledge graph save failed; canonical chunks are intact: {e}")

    # FAISS is disposable acceleration. SQLite has already committed the canonical chunks.
    try:
        vs = VectorStore(user_id=user_id)
        vs.add(embeddings, chunks)
    except Exception as e:
        logger.warning(f"Vector acceleration update failed; rebuild can repair it: {e}")

    logger.info(f"Ingested {fname}: {len(chunks)} chunks, user={user_id}")
    return {
        "success": True,
        "filename": fname,
        "chunks": len(chunks),
        "hash": fhash,
        "profile": profile,
    }


def delete_document(document_hash: str, user_id: str = "global", workspace_id: str = "core") -> dict:
    db_user = storage_user_id(user_id)
    workspace_id = workspace_id or "core"
    try:
        with get_conn() as conn:
            doc = conn.execute(
                """SELECT filename, file_hash FROM documents
                   WHERE user_id = ? AND workspace_id = ? AND file_hash = ?""",
                (db_user, workspace_id, document_hash),
            ).fetchone()
            if not doc:
                return {"success": False, "error": "Document not found"}
            conn.execute(
                "DELETE FROM document_chunks WHERE user_id = ? AND workspace_id = ? AND document_hash = ?",
                (db_user, workspace_id, document_hash),
            )
            conn.execute(
                "DELETE FROM documents WHERE user_id = ? AND workspace_id = ? AND file_hash = ?",
                (db_user, workspace_id, document_hash),
            )
            conn.execute(
                "DELETE FROM document_profiles WHERE user_id = ? AND workspace_id = ? AND document_hash = ?",
                (db_user, workspace_id, document_hash),
            )
            conn.execute(
                "DELETE FROM concept_mentions WHERE user_id = ? AND workspace_id = ? AND document_hash = ?",
                (db_user, workspace_id, document_hash),
            )
            conn.execute(
                "DELETE FROM topic_frequency WHERE user_id = ? AND workspace_id = ? AND document_hash = ?",
                (db_user, workspace_id, document_hash),
            )
        clear_retrieval_cache(user_id, workspace_id)
        rebuilt = VectorStore(user_id=user_id).rebuild_from_sqlite(workspace_id=workspace_id)
        return {"success": True, "filename": doc["filename"], "rebuilt_vectors": rebuilt}
    except Exception as e:
        logger.error(f"Document delete failed for {document_hash}: {e}")
        return {"success": False, "error": str(e)}


def list_documents(user_id: str = "global", workspace_id: str = "") -> list:
    db_user = storage_user_id(user_id)
    try:
        with get_conn() as conn:
            workspace_clause = "AND workspace_id = ?" if workspace_id else ""
            params = (db_user, workspace_id) if workspace_id else (db_user,)
            rows = conn.execute(
                f"SELECT filename, file_type, chunk_count, ingested_at FROM documents WHERE user_id = ? {workspace_clause} ORDER BY ingested_at DESC",
                params,
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []
