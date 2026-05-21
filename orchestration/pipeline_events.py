# Akshay-core
__author__ = "Akshay-core"

# FILE: orchestration/pipeline_events.py
from dataclasses import dataclass, field
from typing import Any


@dataclass


class PipelineEvent:
    type: str
    label: str
    data: dict[str, Any] = field(default_factory=dict)


def event(event_type: str, label: str, **data: Any) -> dict:
    return PipelineEvent(event_type, label, data).__dict__


def is_token_event(item: Any) -> bool:
    return isinstance(item, dict) and item.get("type") == "token"
