# system_audit.py
# Akshay-core
__author__ = "Akshay-core"

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable

from app.database.sqlite_db import get_conn, init_db
from app.database.vector_store import VectorStore
from app.memory.session_memory import storage_user_id
from app.ownership import signature_label


REQUIRED_TABLES = {
    "documents",
    "document_chunks",
    "document_profiles",
    "knowledge_nodes",
    "knowledge_edges",
    "knowledge_clusters",
    "topic_frequency",
    "claim_evidence",
    "retrieval_cache",
    "embedding_cache",
    "vector_index_state",
    "ingestion_jobs",
    "system_audit_reports",
}


@dataclass(frozen=True)
class AuditFinding:
    code: str
    severity: str
    message: str
    detail: dict


def _fingerprint(values: Iterable[str]) -> str:
    payload = "\n".join(sorted(v for v in values if v))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24] if payload else ""


def _chunk_rows(user_id: str, workspace_id: str = "") -> list[dict]:
    db_user = storage_user_id(user_id)
    clause = "AND workspace_id = ?" if workspace_id else ""
    params = (db_user, workspace_id) if workspace_id else (db_user,)
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT id, document_hash, filename, chunk_index, text_hash, workspace_id
                FROM document_chunks
                WHERE user_id = ? {clause}
                ORDER BY document_hash, chunk_index""",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def _schema_findings() -> list[AuditFinding]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    existing = {row["name"] for row in rows}
    missing = sorted(REQUIRED_TABLES - existing)
    if not missing:
        return []
    return [
        AuditFinding(
            "schema.missing_tables",
            "critical",
            "SQLite schema is missing required production tables.",
            {"missing_tables": missing},
        )
    ]


def _sqlite_findings(user_id: str, workspace_id: str = "") -> list[AuditFinding]:
    db_user = storage_user_id(user_id)
    findings: list[AuditFinding] = []
    workspace_clause = "AND workspace_id = ?" if workspace_id else ""
    chunk_workspace_clause = "AND c.workspace_id = ?" if workspace_id else ""
    doc_workspace_clause = "AND d.workspace_id = ?" if workspace_id else ""
    params = (db_user, workspace_id) if workspace_id else (db_user,)
    with get_conn() as conn:
        duplicate_text = conn.execute(
            f"""SELECT text_hash, COUNT(*) AS n
                FROM document_chunks
                WHERE user_id = ? {workspace_clause}
                GROUP BY text_hash HAVING n > 1
                ORDER BY n DESC LIMIT 25""",
            params,
        ).fetchall()
        orphan_chunks = conn.execute(
            f"""SELECT c.id, c.document_hash, c.filename
                FROM document_chunks c
                LEFT JOIN documents d
                  ON d.user_id = c.user_id AND d.file_hash = c.document_hash
                WHERE c.user_id = ? {chunk_workspace_clause} AND d.file_hash IS NULL
                LIMIT 50""",
            params,
        ).fetchall()
        stale_cache = conn.execute(
            """SELECT COUNT(*) AS n FROM retrieval_cache
               WHERE user_id = ? AND expires_at IS NOT NULL AND expires_at < CURRENT_TIMESTAMP""",
            (db_user,),
        ).fetchone()["n"]
        bad_docs = conn.execute(
            f"""SELECT d.file_hash, d.filename, d.chunk_count, COUNT(c.id) AS actual_chunks
                FROM documents d
                LEFT JOIN document_chunks c
                  ON c.user_id = d.user_id AND c.document_hash = d.file_hash
                WHERE d.user_id = ? {doc_workspace_clause}
                GROUP BY d.file_hash, d.filename, d.chunk_count
                HAVING d.chunk_count != actual_chunks
                LIMIT 50""",
            params,
        ).fetchall()

    if duplicate_text:
        findings.append(
            AuditFinding(
                "sqlite.duplicate_chunks",
                "warning",
                "Duplicate canonical chunk text hashes detected.",
                {"duplicates": [dict(row) for row in duplicate_text]},
            )
        )
    if orphan_chunks:
        findings.append(
            AuditFinding(
                "sqlite.orphan_chunks",
                "critical",
                "Canonical chunks exist without a matching document row.",
                {"orphans": [dict(row) for row in orphan_chunks]},
            )
        )
    if stale_cache:
        findings.append(
            AuditFinding(
                "cache.stale_retrieval",
                "info",
                "Expired retrieval cache rows can be cleaned.",
                {"expired_rows": int(stale_cache)},
            )
        )
    if bad_docs:
        findings.append(
            AuditFinding(
                "sqlite.document_chunk_mismatch",
                "critical",
                "Document chunk_count values do not match canonical chunks.",
                {"documents": [dict(row) for row in bad_docs]},
            )
        )
    return findings


def _vector_findings(user_id: str, workspace_id: str = "") -> list[AuditFinding]:
    rows = _chunk_rows(user_id, workspace_id)
    canonical_ids = {row["id"] for row in rows}
    canonical_hash = _fingerprint(canonical_ids)
    store = VectorStore(user_id=user_id)
    snapshot = store.health_snapshot()
    metadata = store.metadata
    metadata_ids = [
        str(item.get("chunk_id") or item.get("id") or "")
        for item in metadata
        if item.get("chunk_id") or item.get("id")
    ]
    metadata_set = set(metadata_ids)
    findings: list[AuditFinding] = []

    if snapshot["vector_count"] != snapshot["metadata_count"]:
        findings.append(
            AuditFinding(
                "vector.count_mismatch",
                "critical",
                "FAISS vector count differs from metadata sidecar count.",
                snapshot,
            )
        )
    if len(metadata_ids) != len(metadata_set):
        findings.append(
            AuditFinding(
                "vector.duplicate_metadata",
                "critical",
                "Duplicate chunk mappings exist in the vector metadata sidecar.",
                {"duplicate_count": len(metadata_ids) - len(metadata_set)},
            )
        )
    missing = sorted(canonical_ids - metadata_set)[:50]
    orphan = sorted(metadata_set - canonical_ids)[:50]
    if missing:
        findings.append(
            AuditFinding(
                "vector.missing_chunk_mappings",
                "critical",
                "Canonical SQLite chunks are missing from the vector sidecar.",
                {"missing_count": len(canonical_ids - metadata_set), "sample": missing},
            )
        )
    if orphan:
        findings.append(
            AuditFinding(
                "vector.orphan_embeddings",
                "critical",
                "Vector sidecar references chunks that are not canonical in SQLite.",
                {"orphan_count": len(metadata_set - canonical_ids), "sample": orphan},
            )
        )
    corrupt = [
        idx for idx, item in enumerate(metadata[:2000])
        if not isinstance(item, dict) or not (item.get("chunk_id") or item.get("id")) or not item.get("text")
    ][:50]
    if corrupt:
        findings.append(
            AuditFinding(
                "vector.corrupted_metadata",
                "critical",
                "Vector metadata rows are malformed or missing required fields.",
                {"sample_indices": corrupt},
            )
        )
    if canonical_hash != snapshot["fingerprint"]:
        findings.append(
            AuditFinding(
                "vector.fingerprint_drift",
                "warning",
                "SQLite and vector fingerprints differ; rebuild recommended.",
                {"sqlite_fingerprint": canonical_hash, "vector_fingerprint": snapshot["fingerprint"]},
            )
        )
    return findings


def run_audit(user_id: str = "global", workspace_id: str = "", repair: bool = False) -> dict:
    init_db()
    findings = _schema_findings()
    findings.extend(_sqlite_findings(user_id, workspace_id))
    findings.extend(_vector_findings(user_id, workspace_id))
    repaired = {}
    if repair and any(f.code.startswith("vector.") for f in findings):
        rebuilt = VectorStore(user_id=user_id).rebuild_from_sqlite(workspace_id=workspace_id)
        repaired["vector_rebuilt_chunks"] = rebuilt
        findings = _schema_findings()
        findings.extend(_sqlite_findings(user_id, workspace_id))
        findings.extend(_vector_findings(user_id, workspace_id))

    severity_order = {"critical": 3, "warning": 2, "info": 1}
    top = max((severity_order.get(f.severity, 0) for f in findings), default=0)
    severity = "critical" if top == 3 else "warning" if top == 2 else "info" if top == 1 else "clean"
    report = {
        "owner": signature_label(),
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "workspace_id": workspace_id or "",
        "severity": severity,
        "finding_count": len(findings),
        "findings": [asdict(f) for f in findings],
        "repair": repaired,
    }
    _persist_report(report)
    return report


def _persist_report(report: dict) -> None:
    report_id = hashlib.sha256(
        json.dumps(report, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:24]
    try:
        user_id = storage_user_id(report["user_id"]) if report.get("user_id") else None
        with get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO system_audit_reports
                   (id, user_id, workspace_id, severity, summary, payload, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (
                    report_id,
                    user_id,
                    report.get("workspace_id", ""),
                    report["severity"],
                    f"{report['finding_count']} findings",
                    json.dumps(report, ensure_ascii=False),
                ),
            )
    except Exception:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit SQLite/FAISS consistency for AI Second Brain.")
    parser.add_argument("--user", default="global", help="User id or username scope to audit.")
    parser.add_argument("--workspace", default="", help="Optional workspace id.")
    parser.add_argument("--repair", action="store_true", help="Rebuild disposable FAISS index from SQLite.")
    parser.add_argument("--json", action="store_true", help="Print full JSON report.")
    args = parser.parse_args()
    report = run_audit(user_id=args.user, workspace_id=args.workspace, repair=args.repair)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Audit severity: {report['severity']} | findings: {report['finding_count']}")
        for finding in report["findings"]:
            print(f"- [{finding['severity']}] {finding['code']}: {finding['message']}")
        if report["repair"]:
            print(f"Repair: {report['repair']}")
    return 1 if report["severity"] == "critical" else 0


if __name__ == "__main__":
    raise SystemExit(main())
