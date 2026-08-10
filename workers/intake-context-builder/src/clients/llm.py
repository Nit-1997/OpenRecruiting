"""LLM gateway client. Replaces clients/anthropic.py.

Per the Lambda mandatory rules in CLAUDE.md, the async client is created per
invocation and closed in run_pipeline's `finally`. That is not optional here:
production/handler.py builds a FRESH EVENT LOOP for every invocation and closes
it, so a transport that outlives the loop it was created on fails on the next
warm invocation with a RuntimeError far from its cause. This module keeps that
lifecycle explicit, exactly as the Anthropic version did.

DELIBERATELY NOT `llm_core.get_client()`. That returns a PROCESS SINGLETON built
once and cached in a module global — correct for the long-lived services (the
backend, voice-agent), wrong here: the second invocation on a warm container
would get back a client whose connection pool is bound to the loop the first
invocation already closed, and llm_core exposes no way to evict it. Constructing
LLMClient() directly gives this worker the per-invocation lifecycle it needs and
leaves the singleton untouched for everyone else.
"""

from __future__ import annotations

from typing import Optional

from llm_core import LLMClient

_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Return this invocation's gateway client. Caller MUST close it in finally."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


async def close_llm_client() -> None:
    """Called from run_pipeline's finally. Closes the transport and resets the
    module global, so the next invocation builds a fresh client on its own loop."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
