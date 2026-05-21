# Akshay-core
__author__ = "Akshay-core"

# FILE: app/core/embeddings.py
import hashlib
import os
from typing import List

import numpy as np

from app.utils.logger import get_logger

logger = get_logger("embeddings")

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

EMBEDDING_DIM = 384
_model = None
_model_load_attempted = False


def _get_model():
    global _model, _model_load_attempted
    if _model is None and not _model_load_attempted:
        _model_load_attempted = True
        try:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)
            logger.info("Embedding model loaded: all-MiniLM-L6-v2")
        except Exception as e:
            logger.warning(f"Embedding model unavailable locally; using deterministic fallback: {e}")
            _model = None
    return _model


def _fallback_embedding(text: str) -> np.ndarray:
    vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    for token in text.lower().split():
        digest = hashlib.blake2b(token.encode("utf-8", errors="ignore"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "little") % EMBEDDING_DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign

    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


def _fallback_embeddings(texts: List[str]) -> np.ndarray:
    return np.vstack([_fallback_embedding(text) for text in texts]).astype(np.float32)


def embed_texts(texts: List[str]) -> np.ndarray:
    if not texts:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    model = _get_model()
    if model is None:
        return _fallback_embeddings(texts)

    vecs = model.encode(texts, show_progress_bar=False, batch_size=32)
    return np.array(vecs, dtype=np.float32)


def embed_query(text: str) -> np.ndarray:
    return embed_texts([text])[0]
