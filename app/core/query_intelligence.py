# Akshay-core
__author__ = "Akshay-core"

# FILE: app/core/query_intelligence.py
import re
from dataclasses import dataclass


@dataclass(frozen=True)


class QueryPlan:
    intent: str
    complexity: str
    retrieval_k: int
    context_budget: int
    answer_budget: int
    refinement_budget: int
    needs_retrieval: bool
    needs_verification: bool
    response_style: str
    streaming_style: str


_SUMMARY_RE = re.compile(r"\b(summarize|summary|tldr|overview|key points|notes)\b", re.I)
_REASONING_RE = re.compile(r"\b(why|how|analyze|reason|evaluate|compare|contrast|strategy|architecture|debug|refactor)\b", re.I)
_WORKFLOW_RE = re.compile(r"\b(make|create|generate|build|plan|workflow|steps|checklist|quiz|flashcards?)\b", re.I)
_FACTUAL_RE = re.compile(r"\b(what|when|who|where|define|list|name|which)\b", re.I)
_CHAT_RE = re.compile(r"^\s*(hi|hello|hey|thanks?|thank you|ok|okay)\s*[.!?]*\s*$", re.I)


def classify_query(query: str) -> QueryPlan:
    text = (query or "").strip()
    length = len(text)

    if _CHAT_RE.match(text):
        return QueryPlan("chat", "micro", 0, 0, 180, 0, False, False, "brief", "direct")

    if _SUMMARY_RE.search(text):
        intent = "summary"
    elif _WORKFLOW_RE.search(text):
        intent = "workflow"
    elif _REASONING_RE.search(text):
        intent = "reasoning"
    elif _FACTUAL_RE.search(text):
        intent = "factual"
    else:
        intent = "factual"

    if length > 1600 or intent in {"reasoning", "workflow"}:
        complexity = "deep"
        retrieval_k = 8
        context_budget = 1700
        answer_budget = 900
        refinement_budget = 380
        streaming_style = "semantic"
    elif length > 500 or intent == "summary":
        complexity = "balanced"
        retrieval_k = 6
        context_budget = 1450
        answer_budget = 720
        refinement_budget = 260
        streaming_style = "structured"
    else:
        complexity = "fast"
        retrieval_k = 5
        context_budget = 1100
        answer_budget = 520
        refinement_budget = 0
        streaming_style = "direct"

    return QueryPlan(
        intent=intent,
        complexity=complexity,
        retrieval_k=retrieval_k,
        context_budget=context_budget,
        answer_budget=answer_budget,
        refinement_budget=refinement_budget,
        needs_retrieval=True,
        needs_verification=intent in {"factual", "reasoning", "summary"},
        response_style="concise" if intent == "factual" else "structured",
        streaming_style=streaming_style,
    )
