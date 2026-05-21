# Akshay-core
__author__ = "Akshay-core"

# FILE: app/core/chunker.py
import hashlib
import re
from typing import List
from app.config import CHUNK_SIZE, CHUNK_OVERLAP


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    # clean up whitespace
    text = re.sub(r'\n{3,}', '\n\n', text.strip())
    text = re.sub(r'[ \t]+', ' ', text)

    # Keep headings attached to nearby paragraphs, then split on sentence boundaries.
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    sentences = []
    for block in blocks:
        if len(block) <= 90 and not re.search(r"[.!?]$", block):
            sentences.append(block)
        else:
            sentences.extend(re.split(r'(?<=[.!?])\s+', block))

    chunks = []
    current = []
    current_len = 0

    for sent in sentences:
        sent_len = len(sent)
        if current_len + sent_len > chunk_size and current:
            chunk = " ".join(current)
            chunks.append(chunk)
            overlap_words = []
            overlap_len = 0
            for prev in reversed(current):
                overlap_words.insert(0, prev)
                overlap_len += len(prev) + 1
                if overlap_len >= overlap:
                    break
            current = overlap_words
            current_len = overlap_len
        current.append(sent)
        current_len += sent_len + 1

    if current:
        chunks.append(" ".join(current))

    # filter empty
    return [c.strip() for c in chunks if len(c.strip()) > 30]


def chunk_with_metadata(text: str, doc_id: str, filename: str) -> List[dict]:
    chunks = chunk_text(text)
    return [
        {
            "chunk_id": f"{doc_id}_chunk_{i}",
            "doc_id": doc_id,
            "filename": filename,
            "text": chunk,
            "chunk_index": i,
            "text_hash": hashlib.sha256(chunk.encode("utf-8", errors="ignore")).hexdigest()[:16],
            "token_estimate": max(1, len(chunk.split())),
        }
        for i, chunk in enumerate(chunks)
    ]
