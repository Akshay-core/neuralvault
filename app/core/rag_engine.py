# FILE: app/core/rag_engine.py
# Akshay-core
__author__ = "Akshay-core"

from concurrent.futures import ThreadPoolExecutor
from typing import Generator, Union
from app.core.context_optimizer import compress_chunks, grounding_confidence
from app.core.evidence_validator import persist_claim_graph
from app.core.knowledge_engine import retrieve_knowledge_context
from app.core.query_intelligence import QueryPlan, classify_query
from app.core.response_synthesis import (
    build_refinement_prompt,
    build_synthesis_prompt,
    paced_semantic_stream,
    prioritize_chunks,
    select_relevant_history,
    semantic_chunks,
    validate_answer,
)
from app.core.retrieval_recovery import recover_retrieval
from app.core.reranker import rerank
from app.core.retriever import retrieve
from app.core.prompt_templates import CHAT_ONLY_TEMPLATE, SYSTEM_PROMPT
from app.models.model_router import pick_model
from app.models.ollama_client import chat
from app.database.sqlite_db import get_conn
from app.memory.session_memory import get_conversation_summary
from app.memory.session_memory import storage_user_id
from app.memory.adaptive_memory import format_memory_context, retrieve_relevant_memories
from app.ownership import signature_label
from app.utils.logger import get_logger
from orchestration.pipeline_events import event
import time

logger = get_logger("rag_engine")
_EXECUTOR = ThreadPoolExecutor(max_workers=3)


def build_messages(
    query: str,
    context: str,
    history: list,
    confidence: dict = None,
    plan: QueryPlan = None,
    memory_summary: str = "",
    adaptive_memory: str = "",
    knowledge_context: str = "",
) -> list:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if memory_summary:
        messages.append(
            {
                "role": "system",
                "content": "Compressed long-chat memory:\n" + memory_summary,
            }
        )
    if adaptive_memory:
        messages.append(
            {
                "role": "system",
                "content": adaptive_memory,
            }
        )
    if knowledge_context:
        messages.append(
            {
                "role": "system",
                "content": knowledge_context,
            }
        )
    # Keep recent turns plus query-relevant older turns to avoid long-chat drift.
    for msg in select_relevant_history(query, history, max_messages=8):
        messages.append(msg)

    if context:
        prompt = build_synthesis_prompt(query, context, confidence or {}, plan or classify_query(query))
    else:
        hist_str = "\n".join(
            f"{m['role'].capitalize()}: {m['content']}"
            for m in history[-4:]
        )
        prompt = CHAT_ONLY_TEMPLATE.format(history=hist_str, message=query)

    messages.append({"role": "user", "content": prompt})
    return messages


def _token_stats(text: str, generation_ms: int) -> dict:
    token_count = max(0, len((text or "").split()))
    seconds = max(generation_ms / 1000, 0.001)
    return {
        "token_count": token_count,
        "token_per_second": round(token_count / seconds, 2),
    }


def _log_query(
    user_id: str,
    query: str,
    model: str,
    chunks: list,
    confidence: dict,
    timings: dict,
    validation: dict,
    workspace_id: str = "core",
) -> None:
    db_user = storage_user_id(user_id)
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO query_logs
                   (user_id, workspace_id, query, response_time_ms, model_used, retrieval_count,
                    retrieval_ms, rerank_ms, compression_ms, grounding_score,
                    validation_unsupported, refined, retry_count, synthesis_ms,
                    generation_ms, token_count, token_per_second, build_signature)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    db_user,
                    workspace_id or "core",
                    query[:500],
                    timings.get("response_time_ms", 0),
                    model,
                    len(chunks),
                    timings.get("retrieval_ms", 0),
                    timings.get("rerank_ms", 0),
                    timings.get("compression_ms", 0),
                    confidence.get("score", 0),
                    validation.get("unsupported_ratio", 0),
                    1 if validation.get("refined") else 0,
                    timings.get("retry_count", 0),
                    timings.get("synthesis_ms", 0),
                    timings.get("generation_ms", 0),
                    timings.get("token_count", 0),
                    timings.get("token_per_second", 0),
                    signature_label(),
                )
            )
    except Exception as exc:
        logger.warning(f"Query telemetry write failed: {exc}")


def _persist_claim_telemetry(user_id: str, workspace_id: str, query: str, validation: dict) -> None:
    claim_graph = validation.get("claim_graph") or {}
    if not claim_graph.get("claims"):
        return
    try:
        persist_claim_graph(user_id, workspace_id, query, claim_graph)
    except Exception as exc:
        logger.warning(f"Claim evidence telemetry write failed: {exc}")


def prepare_answer(
    query: str,
    user_id: str,
    history: list,
    mode_override: str = "",
    conversation_id: str = "",
    workspace_id: str = "core",
) -> dict:
    start = time.time()
    plan = classify_query(query)
    model_future = _EXECUTOR.submit(pick_model, query=query, override=mode_override)
    memory_future = _EXECUTOR.submit(get_conversation_summary, user_id, conversation_id)
    adaptive_memory_future = _EXECUTOR.submit(retrieve_relevant_memories, user_id, query, workspace_id, 5)
    knowledge_future = _EXECUTOR.submit(retrieve_knowledge_context, query, user_id, workspace_id, 8)
    retrieval_start = time.time()
    chunks = retrieve(
        query,
        user_id=user_id,
        top_k=max(plan.retrieval_k * 2, 8),
        workspace_id=workspace_id,
    ) if plan.needs_retrieval else []
    retrieval_ms = int((time.time() - retrieval_start) * 1000)

    rerank_start = time.time()
    ranked = rerank(query, chunks, top_k=plan.retrieval_k) if chunks else []
    ranked = prioritize_chunks(query, ranked, history, plan)
    ranked, recovery = recover_retrieval(query, user_id, ranked, history, plan, workspace_id=workspace_id)
    rerank_ms = int((time.time() - rerank_start) * 1000)

    compression_start = time.time()
    context, selected_chunks = compress_chunks(query, ranked, token_budget=plan.context_budget)
    compression_ms = int((time.time() - compression_start) * 1000)
    confidence = grounding_confidence(selected_chunks)

    model = model_future.result()
    memory_summary = memory_future.result()
    adaptive_memory = format_memory_context(adaptive_memory_future.result())
    knowledge_context, knowledge_graph = knowledge_future.result()
    messages = build_messages(
        query,
        context,
        history,
        confidence=confidence,
        plan=plan,
        memory_summary=memory_summary,
        adaptive_memory=adaptive_memory,
        knowledge_context=knowledge_context,
    )
    timings = {
        "retrieval_ms": retrieval_ms,
        "rerank_ms": rerank_ms,
        "compression_ms": compression_ms,
        "retry_count": recovery.get("retry_count", 0),
        "prep_ms": int((time.time() - start) * 1000),
    }
    return {
        "plan": plan,
        "chunks": selected_chunks,
        "context": context,
        "confidence": confidence,
        "recovery": recovery,
        "memory_summary": memory_summary,
        "adaptive_memory": adaptive_memory,
        "knowledge_graph": knowledge_graph,
        "model": model,
        "messages": messages,
        "timings": timings,
    }


def answer(
    query: str,
    user_id: str = "global",
    history: list = None,
    mode_override: str = "",
    stream: bool = False,
    conversation_id: str = "",
    workspace_id: str = "core",
) -> Union[str, Generator]:
    start = time.time()
    history = history or []

    prepared = prepare_answer(
        query,
        user_id,
        history,
        mode_override=mode_override,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )
    chunks = prepared["chunks"]
    model = prepared["model"]
    messages = prepared["messages"]

    logger.info(f"Query: {query[:80]}... | model={model} | chunks={len(chunks)}")

    if stream:
        return _stream_answer(model, messages)

    generation_start = time.time()
    draft = chat(messages, model=model, stream=False)
    generation_ms = int((time.time() - generation_start) * 1000)
    synthesis_ms = generation_ms
    validation = validate_answer(draft, chunks, prepared["confidence"], prepared["plan"])
    response = draft
    if validation.get("needs_refinement") and prepared["plan"].refinement_budget:
        refine_start = time.time()
        refine_prompt = build_refinement_prompt(
            query,
            prepared["context"],
            draft,
            validation,
            prepared["plan"],
        )
        response = chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": refine_prompt},
            ],
            model=model,
            stream=False,
        )
        synthesis_ms += int((time.time() - refine_start) * 1000)
        validation = validate_answer(response, chunks, prepared["confidence"], prepared["plan"])
        validation["refined"] = True
    else:
        validation["refined"] = False
    _persist_claim_telemetry(user_id, workspace_id, query, validation)
    elapsed = int((time.time() - start) * 1000)

    token_stats = _token_stats(response, generation_ms)
    timings = {
        **prepared["timings"],
        "response_time_ms": elapsed,
        "synthesis_ms": synthesis_ms,
        "generation_ms": generation_ms,
        **token_stats,
    }
    _log_query(user_id, query, model, chunks, prepared["confidence"], timings, validation, workspace_id=workspace_id)

    sources = list({c.get("filename", "") for c in chunks if c.get("filename")})
    return {
        "answer": response,
        "model": model,
        "sources": sources,
        "chunks_used": len(chunks),
        "confidence": prepared["confidence"],
        "validation": validation,
        "recovery": prepared["recovery"],
        "knowledge_graph": prepared.get("knowledge_graph", {}),
        "timings": timings,
        "response_time_ms": elapsed,
    }


def _stream_answer(model: str, messages: list) -> Generator:
    return chat(messages, model=model, stream=True)


def answer_events(
    query: str,
    user_id: str = "global",
    history: list = None,
    mode_override: str = "",
    conversation_id: str = "",
    workspace_id: str = "core",
) -> Generator[dict, None, None]:
    start = time.time()
    history = history or []
    yield event("stage", "Classifying query intent")
    plan = classify_query(query)
    model_future = _EXECUTOR.submit(pick_model, query=query, override=mode_override)
    memory_future = _EXECUTOR.submit(get_conversation_summary, user_id, conversation_id)
    adaptive_memory_future = _EXECUTOR.submit(retrieve_relevant_memories, user_id, query, workspace_id, 5)
    knowledge_future = _EXECUTOR.submit(retrieve_knowledge_context, query, user_id, workspace_id, 8)
    yield event(
        "plan",
        f"Intent: {plan.intent} | complexity: {plan.complexity}",
        intent=plan.intent,
        complexity=plan.complexity,
        retrieval_k=plan.retrieval_k,
    )

    yield event("stage", "Searching knowledge base")
    retrieval_start = time.time()
    chunks = retrieve(
        query,
        user_id=user_id,
        top_k=max(plan.retrieval_k * 2, 8),
        workspace_id=workspace_id,
    ) if plan.needs_retrieval else []
    retrieval_ms = int((time.time() - retrieval_start) * 1000)
    yield event("retrieval", f"Found {len(chunks)} candidate chunks", count=len(chunks), latency_ms=retrieval_ms)

    yield event("stage", "Reranking sources")
    rerank_start = time.time()
    ranked = rerank(query, chunks, top_k=plan.retrieval_k) if chunks else []
    ranked = prioritize_chunks(query, ranked, history, plan)
    ranked, recovery = recover_retrieval(query, user_id, ranked, history, plan, workspace_id=workspace_id)
    rerank_ms = int((time.time() - rerank_start) * 1000)
    yield event("rerank", f"Ranked top {len(ranked)} evidence chunks with priority scoring", count=len(ranked), latency_ms=rerank_ms)
    if recovery.get("retry_count"):
        yield event(
            "recovery",
            f"Low-confidence retrieval detected. Applied {recovery.get('strategy', 'retry')}.",
            retry_count=recovery.get("retry_count", 0),
            strategy=recovery.get("strategy", ""),
        )

    yield event("stage", "Compressing context")
    compression_start = time.time()
    context, selected_chunks = compress_chunks(query, ranked, token_budget=plan.context_budget)
    compression_ms = int((time.time() - compression_start) * 1000)
    confidence = grounding_confidence(selected_chunks)
    yield event(
        "confidence",
        f"Grounding confidence: {confidence['level']} ({confidence['score']})",
        **confidence,
        chunks=[
            {
                "filename": c.get("filename", ""),
                "score": c.get("score", 0),
                "priority_score": c.get("priority_score", 0),
                "confidence": c.get("confidence", "low"),
                "preview": (c.get("compressed_text") or c.get("text", ""))[:260],
            }
            for c in selected_chunks[:5]
        ],
    )

    yield event("stage", "Selecting local model")
    model = model_future.result()
    yield event("model", f"Using {model}", model=model)

    memory_summary = memory_future.result()
    if memory_summary:
        yield event("memory", "Compressed older chat context into focused memory", length=len(memory_summary))
    adaptive_memory = format_memory_context(adaptive_memory_future.result())
    if adaptive_memory:
        yield event("memory", "Selected relevant long-term memories", length=len(adaptive_memory))
    knowledge_context, knowledge_graph = knowledge_future.result()
    if knowledge_context:
        yield event(
            "knowledge",
            f"Mapped {len(knowledge_graph.get('nodes', []))} related knowledge concepts",
            count=len(knowledge_graph.get("nodes", [])),
            confidence_map=knowledge_graph.get("confidence_map", []),
        )
    messages = build_messages(
        query,
        context,
        history,
        confidence=confidence,
        plan=plan,
        memory_summary=memory_summary,
        adaptive_memory=adaptive_memory,
        knowledge_context=knowledge_context,
    )
    yield event("stage", "Synthesizing answer")
    answer_parts = []
    synthesis_start = time.time()
    if plan.complexity == "deep" and plan.refinement_budget:
        yield event("stage", "Drafting answer for validation")
        generation_start = time.time()
        draft = chat(messages, model=model, stream=False)
        generation_ms = int((time.time() - generation_start) * 1000)
        validation = validate_answer(draft, selected_chunks, confidence, plan)
        yield event("validation", validation.get("reason", "Draft checked"), **validation)
        if validation.get("needs_refinement"):
            yield event("stage", "Refining unsupported claims")
            refine_prompt = build_refinement_prompt(query, context, draft, validation, plan)
            final_answer = chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": refine_prompt},
                ],
                model=model,
                stream=False,
            )
            validation = validate_answer(final_answer, selected_chunks, confidence, plan)
            validation["refined"] = True
            yield event("validation", validation.get("reason", "Refined answer checked"), **validation)
        else:
            final_answer = draft
            validation["refined"] = False
        for chunk in semantic_chunks(final_answer):
            answer_parts.append(chunk)
            yield event("token", chunk, token=chunk)
    else:
        validation = {}
        generation_start = time.time()
        for token in paced_semantic_stream(_stream_answer(model, messages), style=plan.streaming_style):
            answer_parts.append(token)
            yield event("token", token, token=token)
        generation_ms = int((time.time() - generation_start) * 1000)
        validation = validate_answer("".join(answer_parts), selected_chunks, confidence, plan)
        validation["refined"] = False
        yield event("validation", validation.get("reason", "Answer checked"), **validation)

    _persist_claim_telemetry(user_id, workspace_id, query, validation)
    elapsed = int((time.time() - start) * 1000)
    synthesis_ms = int((time.time() - synthesis_start) * 1000)
    token_stats = _token_stats("".join(answer_parts), generation_ms)
    sources = list({c.get("filename", "") for c in selected_chunks if c.get("filename")})
    timings = {
        "retrieval_ms": retrieval_ms,
        "rerank_ms": rerank_ms,
        "compression_ms": compression_ms,
        "retry_count": recovery.get("retry_count", 0),
        "response_time_ms": elapsed,
        "synthesis_ms": synthesis_ms,
        "generation_ms": generation_ms,
        **token_stats,
    }
    _log_query(user_id, query, model, selected_chunks, confidence, timings, validation, workspace_id=workspace_id)
    yield event(
        "done",
        "Answer complete",
        answer="".join(answer_parts),
        model=model,
        sources=sources,
        chunks_used=len(selected_chunks),
        confidence=confidence,
        validation=validation,
        recovery=recovery,
        knowledge_graph=knowledge_graph,
        response_time_ms=elapsed,
        timings=timings,
    )
