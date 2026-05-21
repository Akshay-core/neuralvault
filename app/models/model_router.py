# Akshay-core
__author__ = "Akshay-core"

# FILE: app/models/model_router.py
import re
from app.config import RAM_GB, CPU_CORES, MODEL_PROFILES
from app.models.ollama_client import list_available_models
from app.utils.logger import get_logger
from runtime.device_profiler import profile

logger = get_logger("model_router")

_COMPLEXITY_PATTERNS = {
    "heavy": [
        r"\b(explain|analyze|compare|contrast|evaluate|critique|synthesize)\b",
        r"\b(theorem|proof|derive|mathematical|algorithm)\b",
        r"\b(in detail|thoroughly|comprehensive|deep dive|deep thinker|strategy|architecture)\b",
        r"\b(debug|refactor|optimize|security review|threat model)\b",
    ],
    "light": [
        r"\b(hi|hello|hey|thanks?|ok|okay)\b",
        r"\b(what is|define|list|name|when|who|where)\b",
        r"\b(summarize|brief|quick|short)\b",
    ],
    "micro": [
        r"^\s*(hi|hello|hey|yo|ok|okay|thanks?|thank you)\s*[.!?]*\s*$",
        r"^\s*.{1,80}\s*$",
    ],
}


def classify_query(query: str) -> str:
    q = query.lower()
    if len(q) > 1800:
        return "heavy"
    if len(q) > 750:
        return "balanced"
    for tier, patterns in _COMPLEXITY_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, q):
                return tier
    return "balanced"


def normalize_mode(override: str = "") -> str:
    mode = (override or "").strip().lower()
    if mode.startswith("model:"):
        return (override or "").strip()
    if mode in ("safe", "ultra_safe", "instant"):
        return "micro"
    if mode in ("brutal", "performance", "deep"):
        return "heavy"
    return mode


def _available_lookup() -> dict:
    available = list_available_models()
    return {m.lower(): m for m in available}


def _first_available(tier: str, available: dict) -> str:
    profile_data = MODEL_PROFILES[tier]
    candidates = [profile_data["name"], *profile_data.get("aliases", [])]
    for candidate in candidates:
        candidate_lower = candidate.lower()
        for installed_lower, installed in available.items():
            if candidate_lower == installed_lower or candidate_lower in installed_lower:
                return installed
    return profile_data["name"]


def _cap_tier_for_device(tier: str) -> str:
    try:
        p = profile()
        ram_total = p.get("ram_total_gb", RAM_GB)
        ram_used = p.get("ram_used_pct", 0)
        cpu_load = p.get("cpu_usage_pct", 0)
        on_battery = p.get("on_battery", False)
    except Exception:
        ram_total = RAM_GB
        ram_used = cpu_load = 0
        on_battery = False

    order = ["micro", "light", "balanced", "heavy"]
    idx = order.index(tier)
    if ram_total < 6 or CPU_CORES <= 2 or ram_used > 88 or cpu_load > 90:
        idx = min(idx, order.index("micro"))
    elif ram_total < 10 or on_battery:
        idx = min(idx, order.index("light"))
    elif ram_total < 18:
        idx = min(idx, order.index("balanced"))
    return order[idx]


def pick_model(query: str = "", override: str = "") -> str:
    override = normalize_mode(override)
    available = _available_lookup()
    if not available:
        logger.warning("Ollama models unavailable - using light fallback model")
        return MODEL_PROFILES["micro"]["name"]

    if override.startswith("model:"):
        requested = override.split(":", 1)[1].strip().lower()
        for installed_lower, installed in available.items():
            if requested == installed_lower or requested in installed_lower:
                return installed

    complexity = override if override in MODEL_PROFILES else classify_query(query)
    complexity = _cap_tier_for_device(complexity)

    desired = _first_available(complexity, available)
    if desired.lower() in available or any(desired.lower() in m for m in available):
        logger.debug(f"Model selected: {desired} (tier={complexity})")
        return desired

    # fallback chain
    fallback_order = ["micro", "light", "balanced", "heavy"]
    for tier in fallback_order:
        m = _first_available(tier, available)
        if any(m.lower() == av.lower() or m.lower() in av.lower() for av in available.values()):
            logger.warning(f"Fallback to {m}")
            return m

    return next(iter(available.values()), MODEL_PROFILES["micro"]["name"])


def get_model_options(model: str) -> dict:
    model_lower = (model or "").lower()
    for tier, data in MODEL_PROFILES.items():
        names = [data["name"], *data.get("aliases", [])]
        if any(name.lower() in model_lower for name in names):
            return {
                "temperature": data.get("temp", 0.35),
                "num_ctx": data.get("ctx", 2048),
                "num_predict": data.get("num_predict", 640),
            }
    return {"temperature": 0.35, "num_ctx": 2048, "num_predict": 640}
