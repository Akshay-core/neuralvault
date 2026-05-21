# Akshay-core
__author__ = "Akshay-core"

# FILE: plugins/examples/calculator_plugin.py
import sys
import os
import ast
import operator
from plugins.base_plugin import BasePlugin

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# safe eval — no exec, no imports
_ALLOWED_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(expr: str):
    tree = ast.parse(expr.strip(), mode="eval")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        elif isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.BinOp):
            op = _ALLOWED_OPS.get(type(node.op))
            if not op:
                raise ValueError(f"Unsupported op: {node.op}")
            return op(_eval(node.left), _eval(node.right))
        elif isinstance(node, ast.UnaryOp):
            op = _ALLOWED_OPS.get(type(node.op))
            if not op:
                raise ValueError(f"Unsupported op: {node.op}")
            return op(_eval(node.operand))
        else:
            raise ValueError(f"Unsupported node: {type(node)}")

    return _eval(tree)


class CalculatorPlugin(BasePlugin):
    name = "calculator"
    description = "Safely evaluates mathematical expressions"
    version = "1.0.0"

    def validate(self, input_data: dict) -> bool:
        return bool(input_data.get("expression"))

    def execute(self, input_data: dict) -> dict:
        expr = input_data.get("expression", "")
        try:
            result = _safe_eval(expr)
            return {
                "success": True,
                "result": result,
                "expression": expr,
            }
        except Exception as e:
            return {"success": False, "error": f"Calculation error: {e}"}
