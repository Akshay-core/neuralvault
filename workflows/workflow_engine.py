# Akshay-core
__author__ = "Akshay-core"

# FILE: workflows/workflow_engine.py
"""
AI workflow engine — chains nodes (RAG → summarize → quiz → export)
like offline Zapier for AI tasks.
"""
from typing import List, Callable, Any
from app.utils.logger import get_logger

logger = get_logger("workflow_engine")


class WorkflowNode:
    def __init__(self, name: str, fn: Callable, config: dict = None):
        self.name = name
        self.fn = fn
        self.config = config or {}

    def run(self, data: Any) -> Any:
        logger.debug(f"Node running: {self.name}")
        return self.fn(data, **self.config)


class Workflow:
    def __init__(self, name: str):
        self.name = name
        self.nodes: List[WorkflowNode] = []

    def add_node(self, node: WorkflowNode) -> "Workflow":
        self.nodes.append(node)
        return self

    def run(self, initial_input: Any) -> dict:
        data = initial_input
        trace = []
        for node in self.nodes:
            try:
                data = node.run(data)
                trace.append({"node": node.name, "status": "ok"})
            except Exception as e:
                logger.error(f"Workflow {self.name} failed at node {node.name}: {e}")
                trace.append({"node": node.name, "status": "error", "error": str(e)})
                return {"success": False, "trace": trace, "error": str(e)}
        return {"success": True, "result": data, "trace": trace}


# ── Pre-built workflow: RAG → Summarize → Quiz ──────────────────

def build_study_workflow(user_id: str, query: str) -> Workflow:
    from app.core.retriever import retrieve, format_context
    from plugins.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()

    def step_retrieve(q, **_):
        chunks = retrieve(q, user_id=user_id, top_k=5)
        return format_context(chunks)

    def step_summarize(content, **_):
        r = pm.run("pdf_summarizer", {"content": content})
        return r.get("result", content)

    def step_quiz(summary, **_):
        r = pm.run("quiz_generator", {"content": summary, "count": 5})
        return r.get("result", [])

    wf = Workflow("study_workflow")
    wf.add_node(WorkflowNode("retrieve", step_retrieve))
    wf.add_node(WorkflowNode("summarize", step_summarize))
    wf.add_node(WorkflowNode("quiz", step_quiz))
    return wf
