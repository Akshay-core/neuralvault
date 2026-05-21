# Akshay-core
__author__ = "Akshay-core"

# FILE: app/config.py
import os
import psutil
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
MODELS_CACHE = BASE_DIR / "models_cache"

# ── Device detection ──────────────────────────────────────────


def get_ram_gb():
    return psutil.virtual_memory().total / (1024 ** 3)
 

def get_cpu_cores():
    return psutil.cpu_count(logical=False) or 2


def get_device_tier():
    ram = get_ram_gb()
    if ram < 8:
        return "light"
    elif ram < 16:
        return "balanced"
    else:
        return "heavy"


DEVICE_TIER = get_device_tier()
RAM_GB = get_ram_gb()
CPU_CORES = get_cpu_cores()

# ── Model config ──────────────────────────────────────────────
MODEL_PROFILES = {
    "micro": {
        "name": "gemma2:2b",
        "aliases": ["gemma2:2b", "qwen2.5:1.5b", "phi3:mini", "llama3.2:1b"],
        "ctx": 1536,
        "temp": 0.25,
        "num_predict": 384,
    },
    "light": {
        "name": "phi3:mini",
        "aliases": ["phi3:mini", "qwen2.5:3b", "gemma2:2b", "llama3.2:3b"],
        "ctx": 2048,
        "temp": 0.3,
        "num_predict": 640,
    },
    "balanced": {
        "name": "llama3.1:8b",
        "aliases": ["llama3.1:8b", "qwen2.5:7b", "mistral:7b", "llama3:8b"],
        "ctx": 4096,
        "temp": 0.35,
        "num_predict": 960,
    },
    "heavy": {
        "name": "llama3.1:70b",
        "aliases": ["llama3.1:70b", "qwen2.5:14b", "mixtral:8x7b", "deepseek-r1:14b"],
        "ctx": 8192,
        "temp": 0.35,
        "num_predict": 1400,
    },
}

ACTIVE_MODEL = MODEL_PROFILES[DEVICE_TIER]
OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# ── RAG config ────────────────────────────────────────────────
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
TOP_K_RETRIEVAL = 5
VECTOR_INDEX_DIR = DATA_DIR / "vector_index"
PROCESSED_DOCS_DIR = DATA_DIR / "processed_docs"
RAW_DOCS_DIR = DATA_DIR / "raw_docs"

# ── DB ────────────────────────────────────────────────────────
SQLITE_DB_PATH = DATA_DIR / "user_data" / "brain.db"

# ── Security ──────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "local-dev-secret-change-this")
SESSION_TTL_HOURS = 24
MAX_QUERY_LENGTH = 4000

# ── Logging ───────────────────────────────────────────────────
LOG_LEVEL = "INFO"
APP_LOG = LOGS_DIR / "app.log"
ERR_LOG = LOGS_DIR / "errors.log"
PERF_LOG = LOGS_DIR / "performance.log"

# ── Ensure dirs exist ─────────────────────────────────────────
for d in [DATA_DIR, LOGS_DIR, MODELS_CACHE, VECTOR_INDEX_DIR,
          PROCESSED_DOCS_DIR, RAW_DOCS_DIR, DATA_DIR / "user_data"]:
    d.mkdir(parents=True, exist_ok=True)
