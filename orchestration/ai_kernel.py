# Akshay-core
__author__ = "Akshay-core"

# FILE: orchestration/ai_kernel.py
"""
Central control system: safety, intent routing, RAG orchestration, plugins,
streaming events, and durable conversation memory.
"""
import re
from typing import Generator, Union

from app.core.rag_engine import answer as rag_answer
from app.core.rag_engine import answer_events
from app.memory.session_memory import add_message, ensure_conversation, get_history
from app.utils.logger import get_logger
from orchestration.pipeline_events import event
from plugins.plugin_manager import get_plugin_manager
from security.prompt_firewall import check_query, sanitize

logger = get_logger("ai_kernel")

_CALC_RE = re.compile(r"^[\d\s\+\-\*\/\(\)\.\^%]+$")
_QUIZ_RE = re.compile(r"\b(quiz|questions?|test me|flashcards?)\b", re.I)
_SUMM_RE = re.compile(r"\b(summarize|summary|tldr|overview)\b", re.I)
_GREETING_RE = re.compile(r"^\s*(hi|hello|hey|yo|thanks?|thank you|ok|okay)\s*[.!?]*\s*$", re.I)
_COMMANDS = {
    "/summarize": ("summarize", ""),
    "/quiz": ("quiz", ""),
    "/explain": ("rag", "Explain clearly with examples: "),
    "/deepsearch": ("rag", "Deep search and cross-check the knowledge base: "),
    "/fast": ("rag", "Answer briefly and directly: "),
}


def _apply_command(query: str, mode_override: str = "") -> tuple[str, str, str]:
    text = query.strip()
    if not text.startswith("/"):
        return text, mode_override, ""
    command, _, rest = text.partition(" ")
    command = command.lower()
    if command not in _COMMANDS:
        return text, mode_override, ""
    intent, prefix = _COMMANDS[command]
    if command == "/deepsearch":
        mode_override = "heavy"
    elif command == "/fast":
        mode_override = "micro"
    body = rest.strip() or text
    if prefix:
        body = prefix + body
    if intent == "summarize":
        body = "summarize " + body
    elif intent == "quiz":
        body = "quiz " + body
    return body, mode_override, command


def classify_intent(query: str) -> str:
    q = query.strip()
    if _GREETING_RE.match(q):
        return "smalltalk"
    if _CALC_RE.match(q.replace(" ", "")):
        return "calculator"
    if _QUIZ_RE.search(q):
        return "quiz"
    if _SUMM_RE.search(q):
        return "summarize"
    return "rag"


def _persist_result(user_id: str, query: str, result: dict, conversation_id: str) -> None:
    add_message(user_id, "user", query, conversation_id=conversation_id)
    add_message(
        user_id,
        "assistant",
        result.get("answer", ""),
        result.get("model", ""),
        conversation_id=conversation_id,
    )


def _persisting_event_stream(generator: Generator, user_id: str, query: str, conversation_id: str):
    add_message(user_id, "user", query, conversation_id=conversation_id)
    final_answer = ""
    final_model = ""
    for item in generator:
        if isinstance(item, dict) and item.get("type") == "done":
            data = item.get("data", {})
            final_answer = data.get("answer", "")
            final_model = data.get("model", "")
        yield item
    add_message(user_id, "assistant", final_answer, final_model, conversation_id=conversation_id)


def _run_plugin_intent(query: str, user_id: str, intent: str, workspace_id: str = "core") -> dict | None:
    pm = get_plugin_manager()

    if intent == "calculator":
        plugin_result = pm.run("calculator", {"expression": query})
        if plugin_result["success"]:
            return {
                "answer": f"Result: **{plugin_result['result']}**",
                "model": "calculator_plugin",
                "sources": [],
            }
        return None

    if intent == "quiz":
        from app.core.retriever import format_context, retrieve

        chunks = retrieve(query, user_id=user_id, top_k=3, workspace_id=workspace_id)
        content = format_context(chunks) if chunks else query
        plugin_result = pm.run("quiz_generator", {"content": content, "count": 5})
        if plugin_result["success"]:
            questions = plugin_result["result"]
            formatted = "\n\n".join(
                f"**Q{i+1}:** {q['question']}\n**A{i+1}:** {q['answer']}"
                for i, q in enumerate(questions)
            )
            return {
                "answer": f"Quiz generated:\n\n{formatted}",
                "model": plugin_result.get("model_used", ""),
                "sources": list({c.get("filename", "") for c in chunks}),
            }
        return None

    if intent == "summarize":
        from app.core.retriever import format_context, retrieve

        chunks = retrieve(query, user_id=user_id, top_k=5, workspace_id=workspace_id)
        content = format_context(chunks) if chunks else ""
        if not content:
            return None
        plugin_result = pm.run("pdf_summarizer", {"content": content})
        if plugin_result["success"]:
            return {
                "answer": f"Summary:\n\n{plugin_result['result']}",
                "model": plugin_result.get("model_used", ""),
                "sources": list({c.get("filename", "") for c in chunks}),
            }
    return None


def process(
    query: str,
    user_id: str = "global",
    mode_override: str = "",
    stream: bool = False,
    conversation_id: str = "",
    workspace_id: str = "core",
) -> Union[dict, Generator]:
    query = sanitize(query)
    query, mode_override, command = _apply_command(query, mode_override)
    safe, reason = check_query(query)
    if not safe:
        logger.warning(f"Blocked query from {user_id}: {reason}")
        return {"answer": f"Query blocked: {reason}", "model": "none", "sources": [], "blocked": True}

    conversation_id = ensure_conversation(user_id, conversation_id, workspace_id=workspace_id)
    history = get_history(user_id, conversation_id=conversation_id)
    intent = classify_intent(query)
    if command:
        logger.info(f"Command routed: {command} -> {intent}")

    if stream:
        return process_events(query, user_id=user_id, mode_override=mode_override, conversation_id=conversation_id, workspace_id=workspace_id)

    if intent == "smalltalk":
        result = {
            "answer": "Hello! I'm ready. Ask about your documents or tell me what you want to work on.",
            "model": "local_fast_path",
            "sources": [],
        }
        _persist_result(user_id, query, result, conversation_id)
        return result

    if intent in {"calculator", "quiz", "summarize"}:
        result = _run_plugin_intent(query, user_id, intent, workspace_id=workspace_id)
        if result:
            _persist_result(user_id, query, result, conversation_id)
            return result

    result = rag_answer(
        query,
        user_id=user_id,
        history=history,
        mode_override=mode_override,
        stream=False,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )
    if isinstance(result, dict):
        _persist_result(user_id, query, result, conversation_id)
    return result


def process_events(
    query: str,
    user_id: str = "global",
    mode_override: str = "",
    conversation_id: str = "",
    workspace_id: str = "core",
) -> Generator[dict, None, None]:
    query = sanitize(query)
    query, mode_override, command = _apply_command(query, mode_override)
    yield event("stage", "Security scan")
    safe, reason = check_query(query)
    if not safe:
        yield event("blocked", f"Query blocked: {reason}", reason=reason)
        return

    conversation_id = ensure_conversation(user_id, conversation_id, workspace_id=workspace_id)
    history = get_history(user_id, conversation_id=conversation_id)
    intent = classify_intent(query)
    if command:
        yield event("command", f"Command {command} activated", command=command)
    yield event("intent", f"Router intent: {intent}", intent=intent)

    if intent == "smalltalk":
        answer = "Hello! I'm ready. Ask about your documents or tell me what you want to work on."
        result = {"answer": answer, "model": "local_fast_path", "sources": []}
        _persist_result(user_id, query, result, conversation_id)
        yield event("token", answer, token=answer)
        yield event("done", "Answer complete", **result)
        return

    if intent in {"calculator", "quiz", "summarize"}:
        result = _run_plugin_intent(query, user_id, intent, workspace_id=workspace_id)
        if result:
            _persist_result(user_id, query, result, conversation_id)
            yield event("tool", f"Executed {result.get('model', 'tool')}", model=result.get("model", "tool"))
            yield event("token", result.get("answer", ""), token=result.get("answer", ""))
            yield event("done", "Answer complete", **result)
            return
        yield event("stage", "Tool fallback: using RAG")

    stream = answer_events(
        query,
        user_id=user_id,
        history=history,
        mode_override=mode_override,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )
    yield from _persisting_event_stream(stream, user_id, query, conversation_id)
