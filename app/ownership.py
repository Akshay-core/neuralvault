# Akshay-core
__author__ = "Akshay-core"

import hashlib
import json
import os
import platform
import uuid
from datetime import datetime, timezone
from pathlib import Path


OWNER_NAME = "Akshay-core"
APP_BRAND = "AI Second Brain"
AKX_BUILD_SIGNATURE = "Akshay-core-runtime-v4"
SIGNATURE_SCHEMA = "akx-signature-v1"


def _base_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _signature_path() -> Path:
    return _base_dir() / "data" / "akshay_core_signature.json"


def _new_payload() -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    machine_hint = f"{platform.node()}:{platform.system()}:{uuid.getnode()}:{_base_dir()}"
    build_hash = hashlib.sha256(
        f"{OWNER_NAME}|{AKX_BUILD_SIGNATURE}|{machine_hint}".encode("utf-8")
    ).hexdigest()[:20]
    return {
        "owner": OWNER_NAME,
        "brand": APP_BRAND,
        "signature": AKX_BUILD_SIGNATURE,
        "schema": SIGNATURE_SCHEMA,
        "build_fingerprint": f"AKX-{build_hash}",
        "created_at": created_at,
    }


def ownership_payload() -> dict:
    path = _signature_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("owner") == OWNER_NAME and data.get("build_fingerprint"):
                return data
        except Exception:
            pass
    data = _new_payload()
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return data


def build_fingerprint() -> str:
    return str(ownership_payload()["build_fingerprint"])


def signature_label() -> str:
    return f"{OWNER_NAME} | {AKX_BUILD_SIGNATURE} | {build_fingerprint()}"


def export_header(kind: str = "export") -> str:
    return f"{APP_BRAND} {kind} | {signature_label()}"


def signed_metadata(extra: dict | None = None) -> dict:
    payload = ownership_payload()
    data = {
        "akx_owner": payload["owner"],
        "akx_signature": payload["signature"],
        "akx_fingerprint": payload["build_fingerprint"],
        "akx_schema": payload["schema"],
    }
    if extra:
        data.update(extra)
    return data


def is_local_first() -> bool:
    return os.getenv("AI_SECOND_BRAIN_LOCAL_FIRST", "1").strip() != "0"
