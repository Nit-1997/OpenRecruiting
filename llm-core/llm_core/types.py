"""Normalized LLM result shapes. No vendor types cross this boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMReply:
    text: str
    model: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    emulated_tools: bool = False

    def tool_call_named(self, name: str) -> ToolCall | None:
        for call in self.tool_calls:
            if call.name == name:
                return call
        return None
