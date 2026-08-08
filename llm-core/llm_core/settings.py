"""Configuration for reaching the LiteLLM gateway."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, kw_only=True)
class LLMSettings:
    gateway_url: str
    api_key: str
    force_json_tools: frozenset[str]
    timeout_seconds: float


@lru_cache(maxsize=1)
def get_settings() -> LLMSettings:
    raw_forced = os.environ.get("LLM_FORCE_JSON_TOOLS", "")
    forced = frozenset(a.strip() for a in raw_forced.split(",") if a.strip())
    return LLMSettings(
        gateway_url=os.environ.get("LLM_GATEWAY_URL", "http://litellm:4000").rstrip("/"),
        api_key=os.environ.get("LITELLM_MASTER_KEY", ""),
        force_json_tools=forced,
        timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", "60")),
    )
