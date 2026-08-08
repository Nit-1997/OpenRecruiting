"""Errors raised by llm_core. Never surface a bare empty-string message: the
Anthropic-era HTTP invoker did exactly that and produced 'Failed to trigger job: '
in logs, which cost real debugging time.
"""

from __future__ import annotations


class LLMError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        alias: str | None = None,
        status: int | None = None,
        provider: str | None = None,
    ) -> None:
        detail = message or "unknown LLM failure"
        parts = [detail]
        if alias:
            parts.append(f"alias={alias}")
        if status is not None:
            parts.append(f"status={status}")
        if provider:
            parts.append(f"provider={provider}")
        super().__init__(" ".join(parts))
        self.alias = alias
        self.status = status
        self.provider = provider


class ToolEmulationError(LLMError):
    """A model without native tool support failed to return schema-valid JSON."""
