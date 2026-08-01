"""Environment-driven settings for intake-agent-context-builder Lambda."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    environment: str
    anthropic_api_key: str
    anthropic_model_sonnet: str
    supabase_url: str
    supabase_secret_key: str
    cortex_mcp_url: str
    cortex_token_url: str
    internal_api_secret: str
    log_level: str
    log_format: str


def load_settings() -> Settings:
    return Settings(
        environment=os.getenv("ENVIRONMENT", "production"),
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        anthropic_model_sonnet=os.getenv("ANTHROPIC_MODEL_SONNET", "claude-sonnet-4-6"),
        supabase_url=os.environ["SUPABASE_URL"],
        supabase_secret_key=os.environ["SUPABASE_SECRET_KEY"],
        cortex_mcp_url=os.environ["CORTEX_MCP_URL"],
        cortex_token_url=os.environ["CORTEX_TOKEN_URL"],
        internal_api_secret=os.environ["INTERNAL_API_SECRET"],
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_format=os.getenv("LOG_FORMAT", "json"),
    )
