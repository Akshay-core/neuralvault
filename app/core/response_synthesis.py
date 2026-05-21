# FILE: app/core/response_synthesis.py
# Akshay-core
__author__ = "Akshay-core"

import re
import time
from datetime import datetime, timezone
from typing import Iterable

from app.core.evidence_validator import build_claim_graph
from app.core.query_intelligence import QueryPlan


_WORD_RE = re.compile(r"[A-Za-z0-9_]{3,}")
_SOURCE_RE = re.compile(r"\b(source|according to|from|based on|cites?|evidence)\b", re.I)


def _terms(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text or "")}


def _freshness_score(value: str | None) -> float:
    if not value:
        return 0.55
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age_days = max(0, (datetime.now(timezone.utc) - parsed).days)
        if age_days <= 7:
            return 1.0
        if age_days <= 60:
            return 0.82
        if age_days <= 365:
            return 0.66
        return 0.48
    except Exception:
        return 0.55


def _history_terms(history: list[dict], limit: int = 4) -> set[str]:
    recent = " ".join(m.get("content", "") for m in history[-limit:])
    return _terms(recent)


def select_relevant_history(query: str, history: list[dict], max_messages: int = 8) -> list[dict]:
    if not history:
        return []
    query_terms = _terms(query)
    scored = []
    total = len(history)
    for idx, msg in enumerate(history):
        content = msg.get("content", "")
        terms = _terms(content)
        overlap = len(terms & query_terms) / max(len(query_terms), 1) if query_terms else 0
        recency = (idx + 1) / max(total, 1)
        role_weight = 1.0 if msg.get("role") == "user" else 0.88
        score = (overlap * 0.68) + (recency * 0.32)
        scored.append((score * role_weight, idx, msg))

    keep_recent = {(total - i - 1) for i in range(min(4, total))}
    chosen = {idx for _, idx, _ in sorted(scored, reverse=True)[:max_messages]}
    chosen.update(keep_recent)
    return [history[i] for i in sorted(chosen)[-max_messages:]]


def prioritize_chunks(query: str, chunks: list[dict], history: list[dict], plan: QueryPlan) -> list[dict]:
    """Blend retrieval relevance with practical source quality signals."""
    if not chunks:
        return []

    query_terms = _terms(query)
    continuity_terms = _history_terms(history)
    weights = {
        "semantic": 0.42,
        "freshness": 0.10,
        "citation": 0.12,
        "reliability": 0.15,
        "continuity": 0.08,
        "intent": 0.13,
    }
    if plan.intent == "summary":
        weights.update({"semantic": 0.34, "citation": 0.18, "intent": 0.18})
    elif plan.intent == "reasoning":
        weights.update({"semantic": 0.38, "reliability": 0.18, "intent": 0.16})

    enriched = []
    for chunk in chunks:
        text = chunk.get("text", "")
        words = _terms(text)
        semantic = float(chunk.get("score", 0.0))
        freshness = _freshness_score(chunk.get("created_at") or chunk.get("ingested_at"))
        citation_density = min(1.0, (len(_SOURCE_RE.findall(text)) * 0.12) + (0.18 if chunk.get("filename") else 0.0))
        reliability = 0.72
        if chunk.get("text_hash"):
            reliability += 0.12
        if chunk.get("filename"):
            reliability += 0.10
        if len(text.split()) >= 60:
            reliability += 0.06
        reliability = min(1.0, reliability)
        continuity = len(words & continuity_terms) / max(len(continuity_terms), 1) if continuity_terms else 0.35
        intent_alignment = len(words & query_terms) / max(len(query_terms), 1) if query_terms else semantic
        priority = (
            semantic * weights["semantic"]
            + freshness * weights["freshness"]
            + citation_density * weights["citation"]
            + reliability * weights["reliability"]
            + continuity * weights["continuity"]
            + intent_alignment * weights["intent"]
        )
        item = dict(chunk)
        item["priority_score"] = round(priority, 4)
        item["priority_signals"] = {
            "semantic": round(semantic, 3),
            "freshness": round(freshness, 3),
            "citation_density": round(citation_density, 3),
            "reliability": round(reliability, 3),
            "continuity": round(continuity, 3),
            "intent_alignment": round(intent_alignment, 3),
        }
        item["score"] = round((semantic * 0.68) + (priority * 0.32), 4)
        enriched.append(item)

    enriched.sort(key=lambda c: c.get("score", 0.0), reverse=True)
    return enriched


def validate_answer(answer: str, chunks: list[dict], confidence: dict, plan: QueryPlan) -> dict:
    answer_terms = _terms(answer)
    evidence_terms = _terms(" ".join(c.get("compressed_text") or c.get("text", "") for c in chunks))
    unsupported_ratio = 1.0
    if answer_terms:
        unsupported_ratio = 1 - (len(answer_terms & evidence_terms) / max(len(answer_terms), 1))
    citation_present = any((c.get("filename") or "") in answer for c in chunks) or bool(_SOURCE_RE.search(answer))
    claim_graph = build_claim_graph(answer, chunks)
    claim_checks = [
        {
            "claim": c["claim"],
            "support_score": c["support_score"],
            "contradiction_score": c["contradiction_score"],
            "source_agreement": c["source_agreement"],
            "confidence": c["confidence"],
        }
        for c in claim_graph.get("claims", [])
    ]
    weak_claims = [c for c in claim_graph.get("claims", []) if c.get("unsupported") or c.get("evidence_strength", 0) < 0.30]
    contradiction_count = claim_graph.get("metrics", {}).get("contradiction_count", 0)
    retrieval_confidence = claim_graph.get("metrics", {}).get("retrieval_confidence", 0)
    needs_refinement = (
        plan.needs_verification
        and plan.complexity in {"balanced", "deep"}
        and (
            unsupported_ratio > 0.56
            or (chunks and not citation_present)
            or confidence.get("level") == "low"
            or len(weak_claims) >= 2
            or contradiction_count > 0
            or retrieval_confidence < 0.34
        )
    )
    return {
        "unsupported_ratio": round(unsupported_ratio, 3),
        "citation_present": citation_present,
        "claims_checked": claim_checks[:8],
        "claim_graph": claim_graph,
        "weak_claim_count": len(weak_claims),
        "contradiction_count": contradiction_count,
        "contradiction_flag": contradiction_count > 0,
        "retrieval_confidence": retrieval_confidence,
        "source_agreement": claim_graph.get("metrics", {}).get("source_agreement", 0),
        "needs_refinement": needs_refinement,
        "reason": _validation_reason(unsupported_ratio, citation_present, confidence, contradiction_count, retrieval_confidence),
    }


def _extract_claims(answer: str, limit: int = 10) -> list[str]:
    claims = []
    for sent in re.split(r"(?<=[.!?])\s+", answer or ""):
        clean = " ".join(sent.split())
        if len(clean) < 24:
            continue
        if clean.startswith(("-", "*", "#")):
            clean = clean.lstrip("-*# ").strip()
        if clean:
            claims.append(clean[:260])
        if len(claims) >= limit:
            break
    return claims


def _score_claims_against_evidence(claims: list[str], chunks: list[dict]) -> list[dict]:
    evidence = []
    for chunk in chunks:
        text = chunk.get("compressed_text") or chunk.get("text", "")
        evidence.append(
            {
                "filename": chunk.get("filename", ""),
                "chunk_id": chunk.get("chunk_id", ""),
                "terms": _terms(text),
                "preview": text[:220],
            }
        )
    checked = []
    for claim in claims:
        claim_terms = _terms(claim)
        best = {"score": 0.0, "filename": "", "chunk_id": "", "preview": ""}
        for item in evidence:
            overlap = len(claim_terms & item["terms"])
            score = overlap / max(len(claim_terms), 1) if claim_terms else 0.0
            if score > best["score"]:
                best = {
                    "score": score,
                    "filename": item["filename"],
                    "chunk_id": item["chunk_id"],
                    "preview": item["preview"],
                }
        checked.append(
            {
                "claim": claim,
                "support_score": round(best["score"], 3),
                "source": best["filename"],
                "chunk_id": best["chunk_id"],
            }
        )
    return checked


def _validation_reason(
    unsupported_ratio: float,
    citation_present: bool,
    confidence: dict,
    contradiction_count: int = 0,
    retrieval_confidence: float = 0.0,
) -> str:
    if contradiction_count:
        return "Selected evidence contains a contradiction; affected claims must stay low confidence."
    if retrieval_confidence and retrieval_confidence < 0.34:
        return "Claim-to-source mapping is weak; unsupported abstractions should be removed or hedged."
    if confidence.get("level") == "low":
        return "Evidence is thin, so the answer should expose uncertainty."
    if unsupported_ratio > 0.56:
        return "Draft used many terms not seen in the selected evidence."
    if not citation_present:
        return "Draft should cite or name the supporting source."
    return "Draft is adequately grounded."


def build_synthesis_prompt(query: str, context: str, confidence: dict, plan: QueryPlan) -> str:
    evidence_mode = "strict" if confidence.get("level") == "low" else "grounded"
    return f"""Synthesize a final answer using the evidence below.

EVIDENCE MODE: {evidence_mode}
QUERY TYPE: {plan.intent}
ANSWER STYLE: {plan.response_style}
MAX ANSWER BUDGET: about {plan.answer_budget} words

EVIDENCE:
{context}

USER QUESTION:
{query}

Synthesis rules:
- First answer the actual question, then add only useful supporting detail.
- Use source filenames from the evidence when making document-backed claims.
- Mark any claim as low confidence when it cannot be mapped to a supplied chunk or a clear multi-chunk inference.
- If evidence is missing, conflicting, or weak, say that clearly.
- Do not invent consensus, certainty, or production readiness beyond the supplied evidence.
- Do not include hidden chain-of-thought or internal draft notes.

FINAL ANSWER:"""


def build_refinement_prompt(query: str, context: str, draft: str, validation: dict, plan: QueryPlan) -> str:
    return f"""Refine this draft into a more reliable final answer.

USER QUESTION:
{query}

EVIDENCE:
{context}

DRAFT:
{draft}

VALIDATION NOTE:
{validation.get("reason", "Improve grounding and clarity.")}

Refinement rules:
- Remove unsupported claims.
- Add uncertainty where evidence is weak.
- Preserve contradiction warnings when validation found conflicting evidence.
- Cite source filenames for document-backed claims.
- Keep it under about {max(plan.refinement_budget, 220)} words unless the user clearly needs more.

REFINED ANSWER:"""


def semantic_chunks(text: str) -> Iterable[str]:
    """Yield readable chunks for Streamlit instead of raw tiny model tokens."""
    buffer = ""
    for part in re.split(r"(\s+)", text or ""):
        buffer += part
        if len(buffer) >= 42 and (buffer.endswith((" ", "\n")) or re.search(r"[.!?:]\s*$", buffer)):
            yield buffer
            buffer = ""
    if buffer:
        yield buffer


def paced_semantic_stream(tokens: Iterable[str], style: str = "direct") -> Iterable[str]:
    """Convert tiny model tokens into readable live chunks with light pacing."""
    thresholds = {
        "direct": 28,
        "structured": 38,
        "semantic": 48,
    }
    pauses = {
        "direct": 0.0,
        "structured": 0.006,
        "semantic": 0.01,
    }
    threshold = thresholds.get(style, 34)
    pause = pauses.get(style, 0.004)
    buffer = ""
    for token in tokens:
        buffer += token
        should_flush = len(buffer) >= threshold and (
            buffer.endswith((" ", "\n")) or re.search(r"[.!?:;]\s*$", buffer)
        )
        if should_flush:
            if pause:
                time.sleep(pause)
            yield buffer
            buffer = ""
    if buffer:
        yield buffer
