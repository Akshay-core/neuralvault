# FILE: app/core/evidence_validator.py
# Akshay-core
__author__ = "Akshay-core"

import json
import math
import re
from collections import Counter

from app.database.sqlite_db import get_conn
from app.memory.session_memory import storage_user_id


_WORD_RE = re.compile(r"[A-Za-z0-9_]{3,}")
_NEGATION_RE = re.compile(r"\b(no|not|never|without|cannot|can't|won't|isn't|aren't|doesn't|don't)\b", re.I)
_ABSTRACTION_RE = re.compile(
    r"\b(always|never|everyone|nobody|proves?|guarantees?|clearly|obviously|best|worst|"
    r"consensus|all\s+experts|industry\s+standard|production[- ]ready|investor[- ]grade)\b",
    re.I,
)
_HEDGE_RE = re.compile(r"\b(may|might|could|appears|suggests|likely|possibly|roughly|approximately)\b", re.I)
_ANTONYM_PAIRS = (
    ("increase", "decrease"),
    ("increases", "decreases"),
    ("higher", "lower"),
    ("high", "low"),
    ("enabled", "disabled"),
    ("enable", "disable"),
    ("allow", "deny"),
    ("allowed", "denied"),
    ("safe", "unsafe"),
    ("secure", "insecure"),
    ("supported", "unsupported"),
    ("present", "missing"),
    ("success", "failure"),
    ("valid", "invalid"),
)


def _terms(text: str) -> set[str]:
    return {word.lower() for word in _WORD_RE.findall(text or "")}


def _term_vector(text: str) -> Counter:
    return Counter(_terms(text))


def _cosine(left: Counter, right: Counter) -> float:
    if not left or not right:
        return 0.0
    common = set(left) & set(right)
    dot = sum(left[t] * right[t] for t in common)
    left_norm = math.sqrt(sum(v * v for v in left.values()))
    right_norm = math.sqrt(sum(v * v for v in right.values()))
    return dot / max(left_norm * right_norm, 1e-9)


def _ngrams(terms: list[str], n: int) -> set[tuple[str, ...]]:
    if len(terms) < n:
        return set()
    return {tuple(terms[i : i + n]) for i in range(len(terms) - n + 1)}


def _ordered_terms(text: str) -> list[str]:
    return [word.lower() for word in _WORD_RE.findall(text or "")]


def _span_overlap(claim: str, evidence: str) -> float:
    claim_terms = _ordered_terms(claim)
    evidence_terms = _ordered_terms(evidence)
    if not claim_terms or not evidence_terms:
        return 0.0
    best = 0.0
    for n in (4, 3, 2):
        c_ngrams = _ngrams(claim_terms, n)
        if not c_ngrams:
            continue
        e_ngrams = _ngrams(evidence_terms, n)
        best = max(best, len(c_ngrams & e_ngrams) / max(len(c_ngrams), 1))
    return best


def _antonym_conflict(claim_terms: set[str], evidence_terms: set[str]) -> float:
    conflicts = 0
    for left, right in _ANTONYM_PAIRS:
        if (left in claim_terms and right in evidence_terms) or (right in claim_terms and left in evidence_terms):
            conflicts += 1
    return min(0.38, conflicts * 0.19)


def _abstraction_penalty(claim: str, support: float, source_count: int) -> float:
    if not _ABSTRACTION_RE.search(claim):
        return 0.0
    hedged = bool(_HEDGE_RE.search(claim))
    if support >= 0.58 and source_count >= 2:
        return 0.04 if hedged else 0.10
    return 0.22 if hedged else 0.34


def extract_claims(answer: str, limit: int = 12) -> list[str]:
    claims = []
    for sent in re.split(r"(?<=[.!?])\s+", answer or ""):
        clean = " ".join(sent.split()).strip("-*# ")
        if len(clean) < 24:
            continue
        claims.append(clean[:320])
        if len(claims) >= limit:
            break
    return claims


def build_claim_graph(answer: str, chunks: list[dict]) -> dict:
    claims = extract_claims(answer)
    evidence_nodes = []
    for chunk in chunks:
        text = chunk.get("compressed_text") or chunk.get("text", "")
        evidence_nodes.append(
            {
                "chunk_id": chunk.get("chunk_id", ""),
                "filename": chunk.get("filename", ""),
                "source_number": chunk.get("source_number", 0),
                "score": float(chunk.get("score") or 0),
                "terms": _terms(text),
                "vector": _term_vector(text),
                "negated": bool(_NEGATION_RE.search(text)),
                "preview": text[:360],
                "text": text,
            }
        )

    claim_nodes = []
    links = []
    for claim in claims:
        claim_terms = _terms(claim)
        claim_vector = _term_vector(claim)
        claim_negated = bool(_NEGATION_RE.search(claim))
        ranked = []
        for evidence in evidence_nodes:
            overlap = claim_terms & evidence["terms"]
            coverage = len(overlap) / max(len(claim_terms), 1) if claim_terms else 0.0
            semantic = _cosine(claim_vector, evidence["vector"])
            span = _span_overlap(claim, evidence["text"])
            contradiction = 0.0
            if coverage >= 0.22 and claim_negated != evidence["negated"]:
                contradiction = min(1.0, 0.28 + coverage)
            contradiction = min(1.0, contradiction + _antonym_conflict(claim_terms, evidence["terms"]))
            directness = max(coverage, semantic * 0.92, span * 1.08)
            support = min(1.0, directness * 0.68 + span * 0.18 + evidence["score"] * 0.14)
            ranked.append((support, contradiction, evidence, overlap, semantic, span))
        ranked.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        best = ranked[:3]
        source_count = len({item[2]["filename"] for item in best if item[0] >= 0.2 and item[2]["filename"]})
        best_support = best[0][0] if best else 0.0
        contradiction_score = max((item[1] for item in best), default=0.0)
        abstraction_penalty = _abstraction_penalty(claim, best_support, source_count)
        evidence_strength = max(0.0, min(1.0, best_support - abstraction_penalty - contradiction_score * 0.32))
        agreement = min(1.0, source_count / 3 + best_support * 0.35)
        confidence = (
            "high"
            if evidence_strength >= 0.58 and contradiction_score < 0.35 and not abstraction_penalty
            else "medium"
            if evidence_strength >= 0.34 and contradiction_score < 0.55
            else "low"
        )
        unsupported = evidence_strength < 0.30 or contradiction_score >= 0.62
        verdict = "CONTRADICTED" if contradiction_score >= 0.62 else "SUPPORTED" if not unsupported else "UNSUPPORTED / LOW CONFIDENCE"
        claim_id = f"claim_{len(claim_nodes) + 1}"
        claim_nodes.append(
            {
                "id": claim_id,
                "claim": claim,
                "support_score": round(best_support, 3),
                "evidence_strength": round(evidence_strength, 3),
                "contradiction_score": round(contradiction_score, 3),
                "source_agreement": round(agreement, 3),
                "confidence": confidence,
                "unsupported": unsupported,
                "unsupported_abstraction": abstraction_penalty >= 0.2,
                "verdict": verdict,
                "inference_chain": [
                    {
                        "chunk_id": item[2]["chunk_id"],
                        "filename": item[2]["filename"],
                        "support_score": round(item[0], 3),
                    }
                    for item in best
                    if item[0] >= 0.20
                ],
            }
        )
        for support, contradiction, evidence, overlap, semantic, span in best:
            if support <= 0:
                continue
            links.append(
                {
                    "claim_id": claim_id,
                    "chunk_id": evidence["chunk_id"],
                    "filename": evidence["filename"],
                    "support_score": round(support, 3),
                    "contradiction_score": round(contradiction, 3),
                    "semantic_entailment": round(semantic, 3),
                    "span_alignment": round(span, 3),
                    "matched_terms": sorted(overlap)[:16],
                    "preview": evidence["preview"],
                }
            )

    unsupported = sum(1 for claim in claim_nodes if claim["unsupported"])
    contradictions = sum(1 for claim in claim_nodes if claim["contradiction_score"] >= 0.45)
    support_scores = [claim["support_score"] for claim in claim_nodes]
    strength_scores = [claim["evidence_strength"] for claim in claim_nodes]
    avg_support = sum(support_scores) / max(len(support_scores), 1)
    avg_strength = sum(strength_scores) / max(len(strength_scores), 1)
    return {
        "claims": claim_nodes,
        "evidence_links": links,
        "metrics": {
            "claim_count": len(claim_nodes),
            "unsupported_count": unsupported,
            "unsupported_ratio": round(unsupported / max(len(claim_nodes), 1), 3) if claim_nodes else 0.0,
            "contradiction_count": contradictions,
            "average_support": round(avg_support, 3),
            "retrieval_confidence": round(avg_strength, 3),
            "source_agreement": _source_agreement(claim_nodes),
        },
    }


def _source_agreement(claims: list[dict]) -> float:
    if not claims:
        return 0.0
    values = [float(claim.get("source_agreement") or 0) for claim in claims]
    return round(sum(values) / max(len(values), 1), 3)


def persist_claim_graph(
    user_id: str,
    workspace_id: str,
    query: str,
    claim_graph: dict,
) -> None:
    db_user = storage_user_id(user_id)
    rows = []
    links_by_claim: dict[str, list[dict]] = {}
    for link in claim_graph.get("evidence_links", []):
        links_by_claim.setdefault(link["claim_id"], []).append(link)
    for claim in claim_graph.get("claims", []):
        rows.append(
            (
                db_user,
                workspace_id or "core",
                query[:500],
                claim["claim"],
                float(claim.get("support_score") or 0),
                float(claim.get("contradiction_score") or 0),
                float(claim.get("source_agreement") or 0),
                json.dumps(links_by_claim.get(claim["id"], []), ensure_ascii=False),
                1 if claim.get("unsupported") else 0,
            )
        )
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO claim_evidence
               (user_id, workspace_id, query, claim, support_score, contradiction_score,
                source_agreement, supporting_chunks, unsupported)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )


def claim_terms_summary(claim_graph: dict) -> dict:
    counter = Counter()
    for link in claim_graph.get("evidence_links", []):
        counter.update(link.get("matched_terms", []))
    return {"top_matched_terms": counter.most_common(12)}
