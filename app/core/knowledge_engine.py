# FILE: app/core/knowledge_engine.py
# Akshay-core
__author__ = "Akshay-core"

import hashlib
import json
import math
import re
from collections import Counter, defaultdict

from app.database.sqlite_db import get_conn
from app.memory.session_memory import storage_user_id


_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_DATE_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_STOPWORDS = {
    "about", "after", "again", "also", "answer", "because", "before", "between",
    "chapter", "could", "different", "document", "during", "every", "example",
    "following", "from", "have", "into", "more", "most", "only", "other",
    "paper", "papers", "question", "questions", "should", "than", "that",
    "their", "there", "these", "this", "through", "using", "what", "when",
    "where", "which", "with", "would", "year", "your",
}


def _terms(text: str) -> list[str]:
    return [
        t.lower()
        for t in _TERM_RE.findall(text or "")
        if len(t) > 2 and t.lower() not in _STOPWORDS
    ]


def _node_id(user_id: int, workspace_id: str, label: str) -> str:
    raw = f"{user_id}:{workspace_id or 'core'}:{label.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _edge_id(user_id: int, workspace_id: str, left: str, right: str, relation: str) -> str:
    a, b = sorted([left, right])
    raw = f"{user_id}:{workspace_id or 'core'}:{a}:{relation}:{b}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def extract_document_knowledge(text: str, filename: str = "", limit: int = 36) -> dict:
    """Create a local, deterministic document DNA profile.

    This is intentionally heuristic: it gives the system structured handles for
    retrieval and graph traversal without requiring a slow LLM pass on upload.
    """
    words = _terms(text)
    counts = Counter(words)
    bigrams = Counter(
        " ".join(pair)
        for pair in zip(words, words[1:])
        if pair[0] != pair[1] and pair[0] not in _STOPWORDS and pair[1] not in _STOPWORDS
    )
    concepts = []
    for phrase, count in bigrams.most_common(limit):
        if count > 1:
            concepts.append({"label": phrase, "count": count, "type": "topic"})
    for term, count in counts.most_common(limit):
        concepts.append({"label": term, "count": count, "type": "concept"})
    concepts = concepts[:limit]

    domain = _infer_domain(" ".join([filename, " ".join(c["label"] for c in concepts[:12])]))
    density = min(1.0, len(set(words)) / max(len(words), 1) * 18) if words else 0
    dates = sorted(set(_DATE_RE.findall(text or "")))[:20]
    return {
        "domain": domain,
        "concepts": concepts,
        "dates": dates,
        "knowledge_density": round(density, 3),
        "semantic_fingerprint": hashlib.sha256(
            " ".join(c["label"] for c in concepts[:18]).encode("utf-8", errors="ignore")
        ).hexdigest()[:16],
    }


def _infer_domain(text: str) -> str:
    hay = (text or "").lower()
    domain_terms = {
        "psychology": {"psychology", "behavior", "cognitive", "emotion", "habit", "dopamine", "bias"},
        "sales": {"sales", "selling", "customer", "persuasion", "objection", "conversion", "marketing"},
        "technology": {"algorithm", "network", "system", "database", "software", "security", "computer"},
        "business": {"startup", "strategy", "market", "revenue", "growth", "business", "pricing"},
        "study": {"exam", "question", "answer", "chapter", "syllabus", "lecture", "notes"},
    }
    scores = {name: sum(1 for term in terms if term in hay) for name, terms in domain_terms.items()}
    best, score = max(scores.items(), key=lambda item: item[1])
    return best if score else "general"


def save_document_knowledge(user_id: str, workspace_id: str, profile: dict, chunks: list[dict]) -> None:
    db_user = storage_user_id(user_id)
    workspace_id = workspace_id or "core"
    document_hash = profile.get("document_hash", "")
    filename = profile.get("filename", "")
    dna = extract_document_knowledge(
        "\n".join(c.get("text", "") for c in chunks[:80]),
        filename=filename,
    )
    concepts = dna["concepts"]
    if not concepts:
        return

    with get_conn() as conn:
        for item in concepts:
            label = item["label"][:120]
            node_id = _node_id(db_user, workspace_id, label)
            count = int(item.get("count") or 1)
            importance = min(1.0, 0.18 + math.log1p(count) / 5)
            conn.execute(
                """INSERT INTO knowledge_nodes
                   (id, user_id, workspace_id, label, node_type, domain, summary,
                    importance, evidence_count, confidence, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(id) DO UPDATE SET
                     importance = MIN(1.0, knowledge_nodes.importance + excluded.importance * 0.25),
                     evidence_count = knowledge_nodes.evidence_count + excluded.evidence_count,
                     confidence = MIN(1.0, knowledge_nodes.confidence + 0.04),
                     updated_at = CURRENT_TIMESTAMP""",
                (
                    node_id,
                    db_user,
                    workspace_id,
                    label,
                    item.get("type", "concept"),
                    dna["domain"],
                    f"{label} appears in {filename}.",
                    importance,
                    count,
                    min(1.0, 0.35 + importance),
                ),
                )

            conn.execute(
                """INSERT INTO topic_frequency
                   (user_id, workspace_id, topic, document_hash, mention_count, weight, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(user_id, workspace_id, topic, document_hash) DO UPDATE SET
                     mention_count = excluded.mention_count,
                     weight = excluded.weight,
                     updated_at = CURRENT_TIMESTAMP""",
                (
                    db_user,
                    workspace_id,
                    label,
                    document_hash,
                    count,
                    importance,
                ),
            )

            previews = _chunk_previews_for_label(label, chunks, limit=2)
            for chunk in previews:
                conn.execute(
                    """INSERT INTO concept_mentions
                       (user_id, workspace_id, node_id, document_hash, chunk_id, filename,
                        mention_count, evidence_preview)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        db_user,
                        workspace_id,
                        node_id,
                        document_hash,
                        chunk.get("chunk_id", ""),
                        filename,
                        count,
                        chunk.get("text", "")[:360],
                    ),
                )

        top_ids = [_node_id(db_user, workspace_id, c["label"][:120]) for c in concepts[:12]]
        if top_ids:
            cluster_label = concepts[0]["label"][:120]
            cluster_id = hashlib.sha256(
                f"{db_user}:{workspace_id}:{document_hash}:cluster:{cluster_label}".encode("utf-8")
            ).hexdigest()[:24]
            conn.execute(
                """INSERT OR REPLACE INTO knowledge_clusters
                   (id, user_id, workspace_id, label, node_ids, centroid_terms,
                    weight, confidence, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (
                    cluster_id,
                    db_user,
                    workspace_id,
                    cluster_label,
                    json.dumps(top_ids, ensure_ascii=False),
                    json.dumps([c["label"] for c in concepts[:12]], ensure_ascii=False),
                    min(1.0, sum(float(c.get("count") or 1) for c in concepts[:12]) / 80),
                    min(1.0, 0.42 + dna["knowledge_density"] * 0.35),
                ),
            )
        for i, left in enumerate(top_ids):
            for right in top_ids[i + 1 : min(len(top_ids), i + 7)]:
                edge_id = _edge_id(db_user, workspace_id, left, right, "co_occurs_with")
                conn.execute(
                    """INSERT INTO knowledge_edges
                       (id, user_id, workspace_id, source_id, target_id, relation,
                        weight, evidence_count, confidence, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'co_occurs_with', ?, 1, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(id) DO UPDATE SET
                         weight = MIN(1.0, knowledge_edges.weight + excluded.weight * 0.25),
                         evidence_count = knowledge_edges.evidence_count + 1,
                         confidence = MIN(1.0, knowledge_edges.confidence + 0.04),
                         updated_at = CURRENT_TIMESTAMP""",
                    (edge_id, db_user, workspace_id, left, right, 0.24, 0.45),
                )


def _chunk_previews_for_label(label: str, chunks: list[dict], limit: int = 2) -> list[dict]:
    terms = set(_terms(label))
    scored = []
    for chunk in chunks:
        text_terms = set(_terms(chunk.get("text", "")))
        overlap = len(terms & text_terms)
        if overlap:
            scored.append((overlap, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored[:limit]] or chunks[:limit]


def retrieve_knowledge_context(query: str, user_id: str, workspace_id: str = "core", limit: int = 8) -> tuple[str, dict]:
    db_user = storage_user_id(user_id)
    q_terms = set(_terms(query))
    if not q_terms:
        return "", {"nodes": [], "edges": [], "confidence_map": []}

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM knowledge_nodes
               WHERE user_id = ? AND workspace_id = ?
               ORDER BY importance DESC, evidence_count DESC LIMIT 220""",
            (db_user, workspace_id or "core"),
        ).fetchall()

    scored = []
    for row in rows:
        item = dict(row)
        label_terms = set(_terms(" ".join([item.get("label", ""), item.get("summary", ""), item.get("domain", "")])))
        overlap = len(q_terms & label_terms)
        if not overlap:
            continue
        score = (
            overlap / max(len(q_terms), 1) * 0.55
            + float(item.get("importance") or 0) * 0.30
            + float(item.get("confidence") or 0) * 0.15
        )
        item["relevance"] = round(score, 4)
        scored.append(item)
    scored.sort(key=lambda item: item["relevance"], reverse=True)
    nodes = scored[:limit]
    if not nodes:
        return "", {"nodes": [], "edges": [], "confidence_map": []}

    node_ids = [n["id"] for n in nodes]
    placeholders = ",".join("?" for _ in node_ids)
    with get_conn() as conn:
        edges = conn.execute(
            f"""SELECT e.*, s.label AS source_label, t.label AS target_label
                FROM knowledge_edges e
                JOIN knowledge_nodes s ON s.id = e.source_id
                JOIN knowledge_nodes t ON t.id = e.target_id
                WHERE e.user_id = ? AND e.workspace_id = ?
                  AND (e.source_id IN ({placeholders}) OR e.target_id IN ({placeholders}))
                ORDER BY e.weight DESC, e.evidence_count DESC LIMIT 16""",
            (db_user, workspace_id or "core", *node_ids, *node_ids),
        ).fetchall()
        mentions = conn.execute(
            f"""SELECT node_id, filename, chunk_id, evidence_preview, mention_count
                FROM concept_mentions
                WHERE user_id = ? AND workspace_id = ? AND node_id IN ({placeholders})
                ORDER BY mention_count DESC, created_at DESC LIMIT 12""",
            (db_user, workspace_id or "core", *node_ids),
        ).fetchall()

    mention_map = defaultdict(list)
    for row in mentions:
        mention_map[row["node_id"]].append(dict(row))

    lines = ["Structured knowledge signals:"]
    confidence_map = []
    for node in nodes:
        evidence = mention_map.get(node["id"], [])
        evidence_text = "; ".join(
            f"{m.get('filename', '')}: {m.get('evidence_preview', '')[:140]}"
            for m in evidence[:2]
        )
        lines.append(
            f"- {node['label']} ({node.get('domain') or 'general'}, confidence {float(node.get('confidence') or 0):.2f}): "
            f"{node.get('summary') or ''} Evidence: {evidence_text}"
        )
        confidence_map.append(
            {
                "concept": node["label"],
                "confidence": round(float(node.get("confidence") or 0), 3),
                "importance": round(float(node.get("importance") or 0), 3),
                "evidence_count": int(node.get("evidence_count") or 0),
            }
        )
    edge_rows = [dict(e) for e in edges]
    if edge_rows:
        lines.append("Concept links:")
        for edge in edge_rows[:10]:
            lines.append(
                f"- {edge['source_label']} {edge['relation'].replace('_', ' ')} "
                f"{edge['target_label']} (weight {float(edge.get('weight') or 0):.2f})"
            )

    return "\n".join(lines), {"nodes": nodes, "edges": edge_rows, "confidence_map": confidence_map}
