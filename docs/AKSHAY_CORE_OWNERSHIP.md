# Akshay-core Ownership Layer

This project uses professional ownership fingerprinting instead of destructive
or unreadable source obfuscation.

## What Is Embedded

- Python module watermark: `# Akshay-core`
- Python module author: `__author__ = "Akshay-core"`
- Runtime signature: `Akshay-core-runtime-v4`
- Local build fingerprint persisted in `data/akshay_core_signature.json`
- SQLite metadata in `schema_meta`
- Query telemetry signature in `query_logs.build_signature`
- Document/chunk signature in SQLite ingestion tables
- Vector index sidecar metadata in `data/vector_index/*.akx.json`
- UI footer, logs, and exported chat files

## Apply Watermark

Run:

```bash
python scripts/inject_watermark.py
```

The script updates Python files automatically so ownership marking is repeatable
and does not require manual editing.

## Strategy

The goal is not to make the code unreadable. The goal is to make copies
traceable while keeping the system maintainable, debuggable, and credible.
