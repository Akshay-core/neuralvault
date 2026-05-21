# Akshay-core
__author__ = "Akshay-core"

# FILE: plugins/examples/quiz_generator_plugin.py
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from plugins.base_plugin import BasePlugin
from app.core.prompt_templates import QUIZ_TEMPLATE
from app.models.model_router import pick_model
from app.models.ollama_client import generate


class QuizGeneratorPlugin(BasePlugin):
    name = "quiz_generator"
    description = "Generates exam-style questions from document content"
    version = "1.0.0"

    def validate(self, input_data: dict) -> bool:
        return bool(input_data.get("content"))

    def execute(self, input_data: dict) -> dict:
        content = input_data.get("content", "")
        count = input_data.get("count", 5)
        model = pick_model("generate quiz questions")

        prompt = QUIZ_TEMPLATE.format(content=content[:3000], count=count)
        result = generate(prompt, model=model)

        if result.startswith("[ERROR]"):
            return {"success": False, "error": result}

        questions = self._parse_questions(result)
        return {
            "success": True,
            "result": questions,
            "raw": result,
            "model_used": model,
        }

    def _parse_questions(self, raw: str) -> list:
        lines = raw.strip().split("\n")
        questions = []
        current_q = {}
        for line in lines:
            line = line.strip()
            if line.startswith("Q") and ":" in line:
                if current_q:
                    questions.append(current_q)
                current_q = {"question": line.split(":", 1)[1].strip(), "answer": ""}
            elif line.startswith("A") and ":" in line and current_q:
                current_q["answer"] = line.split(":", 1)[1].strip()
        if current_q:
            questions.append(current_q)
        return questions
