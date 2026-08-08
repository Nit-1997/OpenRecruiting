from typing import Any

from llm_core.client import LLMClient, get_client
from llm_core.errors import LLMError, ToolEmulationError
from llm_core.types import LLMReply, ToolCall

__all__ = [
    "LLMClient",
    "LLMError",
    "LLMReply",
    "ToolCall",
    "ToolEmulationError",
    "get_client",
    "llm",
]


def __getattr__(name: str) -> Any:
    """Resolve `llm` on first access rather than at import.

    Services call `llm.complete(...)` against this module-level name. Binding it
    eagerly (`llm = LLMClient()`) would construct AsyncOpenAI and read gateway
    settings during `import llm_core`, so test collection and any process without
    gateway env vars set would fail on an import line. A module __getattr__ keeps
    the ergonomics of a singleton without the import-time side effect, and defers
    to get_client() so both names share one instance.
    """
    if name == "llm":
        return get_client()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
