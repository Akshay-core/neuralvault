# Akshay-core
__author__ = "Akshay-core"

# FILE: app/core/context_optimizer.py
import re
from typing import List


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[A-Za-z0-9_]{2,}")


def _query_terms(query: str) -> set:
    return {w.lower() for w in _WORD_RE.findall(query or "")}


def compress_chunks(query: str, chunks: List[dict], token_budget: int = 1200) -> tuple[str, list]:
    terms = _query_terms(query)
    if not chunks:
        return "", []

    selected = []
    used = 0
    for idx, chunk in enumerate(chunks, start=1):
        text = chunk.get("text", "")
        sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
        if not sentences:
            sentences = [text.strip()]

        scored = []
        for sent in sentences:
            words = {w.lower() for w in _WORD_RE.findall(sent)}
            overlap = len(words & terms)
            density = overlap / max(len(words), 1)
            scored.append((overlap + density, sent))

        scored.sort(key=lambda item: item[0], reverse=True)
        kept = [sent for score, sent in scored[:3] if sent]
        if not kept:
            kept = sentences[:2]

        compressed = " ".join(kept)
        estimate = max(1, len(compressed.split()))
        if selected and used + estimate > token_budget:
            break
        used += estimate

        enriched = dict(chunk)
        enriched["compressed_text"] = compressed
        enriched["source_number"] = idx
        selected.append(enriched)

    context_parts = []
    for item in selected:
        src = item.get("filename", "unknown")
        confidence = item.get("confidence", "unknown")
        score = item.get("score", 0)
        context_parts.append(
            f"[Source {item['source_number']}: {src} | confidence={confidence} | score={score}]\n"
            f"{item.get('compressed_text', item.get('text', ''))}"
        )

    return "\n\n---\n\n".join(context_parts), selected


def grounding_confidence(chunks: List[dict]) -> dict:
    if not chunks:
        return {"level": "low", "score": 0.0, "reason": "No retrieved evidence."}

    avg = sum(c.get("score", 0.0) for c in chunks) / max(len(chunks), 1)
    high = sum(1 for c in chunks if c.get("confidence") == "high")
    medium = sum(1 for c in chunks if c.get("confidence") == "medium")
    coverage = min(1.0, (high * 0.28) + (medium * 0.16) + (len(chunks) * 0.08))
    score = round((avg * 0.65) + (coverage * 0.35), 3)

    if score >= 0.62:
        level = "high"
    elif score >= 0.38:
        level = "medium"
    else:
        level = "low"
    return {"level": level, "score": score, "reason": f"{len(chunks)} sources, avg relevance {avg:.2f}."}
