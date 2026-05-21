# Architecture Audit

Owner: Akshay-core  
Build identity: local-first AI Second Brain

## Current Architecture Map

- `app/ui/streamlit_app.py`: Streamlit workspace shell, chat surface, source display, memory and ingestion controls.
- `app/core/`: query planning, retrieval, reranking, context compression, graph context, answer synthesis, evidence validation.
- `app/database/`: SQLite canonical store and FAISS acceleration sidecar.
- `app/ingestion/`: PDF/text extraction, document profiling, chunking, embedding, graph extraction.
- `app/memory/`: session summaries, workspace state, adaptive memory and retrieval cache.
- `orchestration/`: event pipeline and command kernel.
- `plugins/`: local plugin API and subprocess execution path.
- `security/`: prompt firewall.
- `analytics/`: local usage and latency telemetry.

## Critical Weaknesses Found

- SQLite and FAISS were still vulnerable to write-order drift during ingestion.
- Schema evolution was embedded directly in `init_db` without an audit tool to verify production invariants.
- Evidence validation existed, but was mostly lexical and not persisted as reusable claim telemetry.
- Knowledge graph tables existed, but topic frequency and cluster substrate were missing.
- Document deletion did not provide a first-class canonical delete plus vector rebuild path.
- Plugin execution is partially sandboxed, but still needs manifests, permission scopes, import allowlists, and filesystem boundaries.
- UI remains a large Streamlit surface; it needs component boundaries for Evidence Canvas, Research Cockpit, Memory Center, and RAG Debugger.
- Test coverage is too narrow for retrieval drift, ingestion recovery, memory consistency, and grounded answer validation.

## Completed Slice

- SQLite is now treated as the canonical chunk/document registry during ingestion.
- FAISS updates happen after SQLite commit and are repairable by rebuild.
- Added `system_audit.py` for schema, SQLite, cache, and FAISS consistency checks.
- Added vector index state tracking.
- Added document delete support with vector rebuild.
- Added `knowledge_clusters` and `topic_frequency` persistence.
- Added structured claim/evidence validation and local claim telemetry persistence.

## Execution Roadmap

1. Canonical storage hardening
   - Finish migrations module instead of expanding `init_db`.
   - Add orphan cleanup commands and dry-run repair plans.
   - Add workspace-scoped vector rebuild and deletion tests.

2. Retrieval quality
   - Split retrieval into query understanding, graph traversal, semantic search, lexical search, MMR, rerank, evidence filtering.
   - Add retrieval explanation objects consumed by UI.
   - Add benchmark queries with expected source sets.

3. Evidence-grounded synthesis
   - Upgrade claim alignment with sentence-level evidence spans.
   - Add contradiction heuristics by source and negation pattern.
   - Surface unsupported claim ratio in UI and logs.

4. Ingestion intelligence
   - Replace basic chunking with heading-aware, table-aware, and code-aware chunk models.
   - Add resumable background ingestion jobs.
   - Add document fingerprint, trust score, topic distribution, and density tests.

5. Memory rebuild
   - Separate episodic, semantic, workspace, goal, and preference memory tables.
   - Add decay, merge, conflict resolution, and salience tuning.

6. Security hardening
   - Require plugin manifests.
   - Add permission scopes, subprocess timeouts per plugin, path boundaries, import deny/allow lists, and log redaction.

7. Premium modular UX
   - Break Streamlit monolith into components.
   - Add Evidence Canvas, RAG Debugger, Reasoning Trace Viewer, Ingestion Studio, Model Hub, Memory Center.

8. Evaluation and benchmarks
   - Add retrieval, hallucination, ingestion stress, memory consistency, workspace isolation, and audit repair suites.

## Production Principle

Every new intelligence feature must expose the evidence or state it used. If the system cannot prove a claim from local sources, it should lower confidence or say it does not know.
