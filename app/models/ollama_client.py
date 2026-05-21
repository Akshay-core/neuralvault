# Akshay-core
__author__ = "Akshay-core"

# FILE: app/models/ollama_client.py
import requests
import json
import time
from typing import Generator, Optional
from app.config import OLLAMA_BASE_URL, MODEL_PROFILES
from app.utils.logger import get_logger

logger = get_logger("ollama_client")

_STATUS_CACHE = {"value": False, "expires": 0.0}
_MODELS_CACHE = {"value": [], "expires": 0.0}
_STATUS_TTL_SECONDS = 10
_MODELS_TTL_SECONDS = 30


def _model_options(model: str) -> dict:
    model_lower = (model or "").lower()
    for data in MODEL_PROFILES.values():
        names = [data["name"], *data.get("aliases", [])]
        if any(name.lower() in model_lower for name in names):
            return {
                "temperature": data.get("temp", 0.35),
                "num_ctx": data.get("ctx", 2048),
                "num_predict": data.get("num_predict", 640),
            }
    return {"temperature": 0.35, "num_ctx": 2048, "num_predict": 640}


def is_ollama_running() -> bool:
    now = time.time()
    if now < _STATUS_CACHE["expires"]:
        return _STATUS_CACHE["value"]

    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=1)
        ok = r.status_code == 200
    except Exception:
        ok = False

    _STATUS_CACHE.update({"value": ok, "expires": now + _STATUS_TTL_SECONDS})
    return ok


def list_available_models() -> list:
    now = time.time()
    if now < _MODELS_CACHE["expires"]:
        return _MODELS_CACHE["value"]

    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=1)
        r.raise_for_status()
        data = r.json()
        models = [m["name"] for m in data.get("models", [])]
        ok = True
    except Exception:
        models = []
        ok = False

    _MODELS_CACHE.update({"value": models, "expires": now + _MODELS_TTL_SECONDS})
    _STATUS_CACHE.update({"value": ok, "expires": now + _STATUS_TTL_SECONDS})
    return models


def generate(prompt: str, model: str, system: str = "", stream: bool = False) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
        "keep_alive": "10m",
        "options": _model_options(model),
    }
    if system:
        payload["system"] = system

    try:
        if stream:
            return _stream_generate(payload)
        else:
            r = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=120)
            r.raise_for_status()
            return r.json().get("response", "").strip()
    except requests.exceptions.ConnectionError:
        return "[ERROR] Ollama is not running. Start it with: `ollama serve`"
    except Exception as e:
        logger.error(f"Generation error: {e}")
        return f"[ERROR] {e}"


def _stream_generate(payload: dict) -> Generator[str, None, None]:
    with requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={**payload, "stream": True},
        stream=True,
        timeout=180
    ) as r:
        for line in r.iter_lines():
            if line:
                try:
                    chunk = json.loads(line)
                    tok = chunk.get("response", "")
                    if tok:
                        yield tok
                    if chunk.get("done"):
                        break
                except Exception:
                    continue


def chat(messages: list, model: str, stream: bool = False) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "keep_alive": "10m",
        "options": _model_options(model),
    }
    try:
        if stream:
            return _stream_chat(payload)
        r = requests.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=120)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "").strip()
    except requests.exceptions.ConnectionError:
        return "[ERROR] Ollama is not running. Start it with: `ollama serve`"
    except Exception as e:
        return f"[ERROR] {e}"


def _stream_chat(payload: dict) -> Generator[str, None, None]:
    with requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={**payload, "stream": True},
        stream=True,
        timeout=180
    ) as r:
        for line in r.iter_lines():
            if line:
                try:
                    chunk = json.loads(line)
                    tok = chunk.get("message", {}).get("content", "")
                    if tok:
                        yield tok
                    if chunk.get("done"):
                        break
                except Exception:
                    continue
