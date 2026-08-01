"""Anthropic client wrapper. NOTE: per Lambda mandatory rules in CLAUDE.md,
the async client is created per-invocation and closed in process_pipeline's finally.
"""

from __future__ import annotations

from typing import Optional

from anthropic import AsyncAnthropic

_async_client: Optional[AsyncAnthropic] = None


def get_anthropic_client(api_key: str) -> AsyncAnthropic:
    """Return a process-scoped async Anthropic client. Caller MUST aclose it in finally."""
    global _async_client
    if _async_client is None:
        _async_client = AsyncAnthropic(api_key=api_key, max_retries=2)
    return _async_client


async def close_anthropic_client() -> None:
    """Called from pipeline.run_pipeline's finally block. Resets module global."""
    global _async_client
    if _async_client is not None:
        try:
            await _async_client.close()
        except Exception:
            pass
        _async_client = None
