# Akshay-core
__author__ = "Akshay-core"

# FILE: security/prompt_firewall.py
import re
from typing import Tuple, Dict
from app.utils.logger import get_logger

logger = get_logger("security")

# injection patterns
_INJECTION_PATTERNS = [
    r"ignore\s+.{0,30}(instructions?|rules?|system\s+prompt)",
    r"previous\s+instructions",
    r"you\s+are\s+now\b|act\s+as\s+(if|a\b|an?\b)|pretend\s+(you\s+are|to\s+be)",
    r"\b(jailbreak|bypass|override|disable)\b.{0,20}(safety|filter|restriction)",
    r"\bDAN\b|\bdo\s+anything\s+now\b|developer\s+mode",
    r"forget\s+.{0,20}(training|instructions?|guidelines?)",
    r"(reveal|show|print|output)\s+.{0,20}(system\s+prompt|instructions?)",
    r"prompt\s+injection",
]

_HARMFUL_PATTERNS = [
    r"\b(bomb|explosive|weapon|poison|hack|malware|ransomware)\b.{0,30}(make|create|build|how to)",
    r"how to (harm|hurt|kill|attack|exploit)",
]

_FRAUD_PATTERNS = [
    r"\b(otp|one[-\s]?time password|cvv|card number|upi pin|bank pin|password|seed phrase|private key)\b",
    r"\b(urgent|limited time|act now|verify now|account locked|suspended)\b",
    r"\b(refund|cashback|prize|lottery|gift card|crypto|investment)\b.{0,40}\b(send|pay|transfer|deposit|claim)\b",
    r"\b(anydesk|teamviewer|remote access|screen share)\b",
    r"\b(phishing|scam|fraud|spoof|impersonat(e|ion))\b",
]

_COMPILED_INJECTION = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]
_COMPILED_HARMFUL = [re.compile(p, re.IGNORECASE) for p in _HARMFUL_PATTERNS]
_COMPILED_FRAUD = [re.compile(p, re.IGNORECASE) for p in _FRAUD_PATTERNS]


def analyze_risk(query: str) -> Dict[str, object]:
    """Return a lightweight local risk scan for prompts, scams, and harmful requests."""
    text = query or ""
    signals = []
    score = 0

    for name, patterns, weight in (
        ("prompt injection", _COMPILED_INJECTION, 45),
        ("harmful request", _COMPILED_HARMFUL, 55),
        ("fraud/scam indicator", _COMPILED_FRAUD, 22),
    ):
        matches = sum(1 for pattern in patterns if pattern.search(text))
        if matches:
            score += min(matches * weight, 70)
            signals.append(name)

    if len(text) > 3500:
        score += 15
        signals.append("oversized prompt")

    score = min(score, 100)
    if score >= 70:
        level = "critical"
    elif score >= 35:
        level = "elevated"
    elif score > 0:
        level = "watch"
    else:
        level = "clean"

    return {"score": score, "level": level, "signals": sorted(set(signals))}


def check_query(query: str) -> Tuple[bool, str]:
    """
    Returns (is_safe, reason)
    """
    if not query or not query.strip():
        return False, "Empty query"

    if len(query) > 4000:
        return False, "Query too long"

    risk = analyze_risk(query)

    for pattern in _COMPILED_INJECTION:
        if pattern.search(query):
            logger.warning(f"Injection attempt detected: {query[:80]}")
            return False, "Potential prompt injection detected"

    for pattern in _COMPILED_HARMFUL:
        if pattern.search(query):
            logger.warning(f"Harmful query detected: {query[:80]}")
            return False, "Potentially harmful query"

    if risk["score"] >= 85:
        logger.warning(f"High fraud risk detected: {query[:80]}")
        return False, "High-risk fraud or credential request detected"

    return True, "ok"


def sanitize(text: str) -> str:
    # strip null bytes and control chars
    text = text.replace("\x00", "").strip()
    text = re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text
