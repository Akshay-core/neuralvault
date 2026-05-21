# Akshay-core
__author__ = "Akshay-core"

# FILE: plugins/examples/pdf_summarizer_plugin.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from plugins.base_plugin import BasePlugin
from app.core.prompt_templates import SUMMARIZE_TEMPLATE
from app.models.model_router import pick_model
from app.models.ollama_client import generate


class PDFSummarizerPlugin(BasePlugin):
    name = "pdf_summarizer"
    description = "Summarizes document content into key points"
    version = "1.0.0"

    def validate(self, input_data: dict) -> bool:
        return bool(input_data.get("content"))

    def execute(self, input_data: dict) -> dict:
        content = input_data.get("content", "")[:4000]
        model = pick_model("summarize document")
        prompt = SUMMARIZE_TEMPLATE.format(content=content)
        result = generate(prompt, model=model)
        if result.startswith("[ERROR]"):
            return {"success": False, "error": result}
        return {"success": True, "result": result, "model_used": model}
