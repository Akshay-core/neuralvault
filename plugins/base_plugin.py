# Akshay-core
__author__ = "Akshay-core"

# FILE: plugins/base_plugin.py
from abc import ABC, abstractmethod
from typing import Any


class BasePlugin(ABC):
    name: str = "base"
    description: str = ""
    version: str = "1.0.0"

    @abstractmethod
    def execute(self, input_data: dict) -> dict:
        """
        input_data: arbitrary dict of inputs
        returns: {"success": bool, "result": Any, "error": str}
        """
        pass

    def validate(self, input_data: dict) -> bool:
        return True

    def info(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
        }
