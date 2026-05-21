# FILE: app/database/vector_store.py
# Akshay-core
__author__ = "Akshay-core"

import hashlib
import json
import os
import pickle
import re
import numpy as np
from pathlib import Path
from typing import List, Tuple
from app.core.embeddings import embed_texts
from app.database.sqlite_db import get_conn
from app.memory.session_memory import storage_user_id
from app.ownership import signed_metadata

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False

INDEX_DIR = Path(os.getenv("VECTOR_INDEX_DIR", "data/vector_index"))
INDEX_DIR.mkdir(parents=True, exist_ok=True)


def _safe_user_id(user_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(user_id or "global"))
    return safe[:80] or "global"


class VectorStore:
    def __init__(self, user_id: str = "global", dim: int = 384):
        self.raw_user_id = user_id
        try:
            self.db_user_id = storage_user_id(user_id)
            self.user_id = _safe_user_id(str(self.db_user_id))
        except Exception:
            self.db_user_id = None
            self.user_id = _safe_user_id(user_id)
        self.dim = dim
        self.index_path = INDEX_DIR / f"{self.user_id}.index"
        self.meta_path = INDEX_DIR / f"{self.user_id}.jsonl"
        self.legacy_meta_path = INDEX_DIR / f"{self.user_id}.meta"
        self.signature_path = INDEX_DIR / f"{self.user_id}.akx.json"
        self.index = None
        self.metadata: List[dict] = []
        self._load()

    def _load(self):
        if not FAISS_AVAILABLE:
            self.index = None
            return
        if self.index_path.exists() and self.meta_path.exists():
            self.index = faiss.read_index(str(self.index_path))
            self.metadata = self._load_jsonl_metadata()
        elif self.index_path.exists() and self.legacy_meta_path.exists():
            self.index = faiss.read_index(str(self.index_path))
            self.metadata = self._load_legacy_metadata()
            self._save()
        else:
            self.index = faiss.IndexFlatL2(self.dim)

    def _load_jsonl_metadata(self) -> List[dict]:
        rows = []
        try:
            with open(self.meta_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        rows.append(json.loads(line))
        except Exception:
            rows = []
        return rows

    def _load_legacy_metadata(self) -> List[dict]:
        try:
            with open(self.legacy_meta_path, "rb") as f:
                data = pickle.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save(self, workspace_id: str = "core"):
        if not FAISS_AVAILABLE or self.index is None:
            return
        faiss.write_index(self.index, str(self.index_path))
        with open(self.meta_path, "w", encoding="utf-8", newline="\n") as f:
            for item in self.metadata:
                f.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
        with open(self.signature_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(signed_metadata({"user_scope": self.user_id}), sort_keys=True) + "\n")
        self._record_index_state(status="saved", workspace_id=workspace_id)

    def _metadata_fingerprint(self) -> str:
        chunk_ids = sorted(str(item.get("chunk_id") or item.get("id") or "") for item in self.metadata)
        payload = "\n".join(chunk_id for chunk_id in chunk_ids if chunk_id)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24] if payload else ""

    def _record_index_state(self, status: str, workspace_id: str = "core") -> None:
        if self.db_user_id is None:
            return
        try:
            with get_conn() as conn:
                conn.execute(
                    """INSERT INTO vector_index_state
                       (user_id, workspace_id, index_path, metadata_path, chunk_count,
                        metadata_count, vector_count, content_fingerprint, status,
                        last_rebuilt_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                       ON CONFLICT(user_id, workspace_id) DO UPDATE SET
                         index_path = excluded.index_path,
                         metadata_path = excluded.metadata_path,
                         chunk_count = excluded.chunk_count,
                         metadata_count = excluded.metadata_count,
                         vector_count = excluded.vector_count,
                         content_fingerprint = excluded.content_fingerprint,
                         status = excluded.status,
                         last_rebuilt_at = CASE
                           WHEN excluded.status = 'rebuilt' THEN CURRENT_TIMESTAMP
                           ELSE vector_index_state.last_rebuilt_at
                         END,
                         updated_at = CURRENT_TIMESTAMP""",
                    (
                        self.db_user_id,
                        workspace_id or "core",
                        str(self.index_path),
                        str(self.meta_path),
                        len(self.metadata),
                        len(self.metadata),
                        self.count(),
                        self._metadata_fingerprint(),
                        status,
                    ),
                )
        except Exception:
            return

    def add(self, embeddings: np.ndarray, meta_list: List[dict]):
        if not FAISS_AVAILABLE:
            return
        if embeddings.dtype != np.float32:
            embeddings = embeddings.astype(np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / np.maximum(norms, 1e-12)
        self.index.add(embeddings)
        self.metadata.extend([signed_metadata(item) for item in meta_list])
        workspaces = {str(item.get("workspace_id") or "core") for item in meta_list}
        self._save(workspace_id=workspaces.pop() if len(workspaces) == 1 else "mixed")

    def search(self, query_vec: np.ndarray, top_k: int = 5) -> List[Tuple[float, dict]]:
        if not FAISS_AVAILABLE or self.index is None or self.index.ntotal == 0:
            return []
        if query_vec.dtype != np.float32:
            query_vec = query_vec.astype(np.float32)
        if query_vec.ndim == 1:
            query_vec = query_vec.reshape(1, -1)
        norms = np.linalg.norm(query_vec, axis=1, keepdims=True)
        query_vec = query_vec / np.maximum(norms, 1e-12)
        k = min(top_k, self.index.ntotal)
        distances, indices = self.index.search(query_vec, k)
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < len(self.metadata):
                results.append((float(dist), self.metadata[idx]))
        return results

    def count(self) -> int:
        if self.index is None:
            return 0
        return self.index.ntotal

    def reset(self):
        if FAISS_AVAILABLE:
            self.index = faiss.IndexFlatL2(self.dim)
        self.metadata = []
        self._save()

    def rebuild_from_sqlite(self, workspace_id: str = "") -> int:
        """Rebuild FAISS from canonical SQLite chunks.

        SQLite owns documents and chunks. FAISS is only a disposable acceleration
        layer, so corruption or metadata drift should be fixed by rebuilding.
        """
        if not FAISS_AVAILABLE:
            return 0
        db_user = self.db_user_id if self.db_user_id is not None else storage_user_id(self.raw_user_id)
        workspace_clause = "AND workspace_id = ?" if workspace_id else ""
        params = (db_user, workspace_id) if workspace_id else (db_user,)
        with get_conn() as conn:
            rows = conn.execute(
                f"""SELECT id, document_hash, filename, chunk_index, text, token_estimate,
                           text_hash, workspace_id, created_at
                    FROM document_chunks
                    WHERE user_id = ? {workspace_clause}
                    ORDER BY document_hash, chunk_index""",
                params,
            ).fetchall()
        self.index = faiss.IndexFlatL2(self.dim)
        self.metadata = []
        if not rows:
            self._save(workspace_id=workspace_id or "core")
            return 0
        meta = []
        texts = []
        for row in rows:
            item = dict(row)
            item["chunk_id"] = item.pop("id")
            item["doc_id"] = item.get("document_hash", "")
            texts.append(item.get("text", ""))
            meta.append(item)
        embeddings = embed_texts(texts)
        self.add(embeddings, meta)
        self._record_index_state(status="rebuilt", workspace_id=workspace_id or "core")
        return len(meta)

    def delete_document(self, document_hash: str, workspace_id: str = "") -> int:
        """Remove a document from the disposable FAISS layer by rebuilding SQLite truth."""
        return self.rebuild_from_sqlite(workspace_id=workspace_id)

    def health_snapshot(self) -> dict:
        return {
            "faiss_available": FAISS_AVAILABLE,
            "index_path": str(self.index_path),
            "metadata_path": str(self.meta_path),
            "vector_count": self.count(),
            "metadata_count": len(self.metadata),
            "fingerprint": self._metadata_fingerprint(),
        }
