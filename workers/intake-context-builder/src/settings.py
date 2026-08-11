"""Environment-driven settings for intake-agent-context-builder Lambda."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    environment: str
    # GATEWAY ALIASES, not provider model ids. Two, not one: parse_jd and
    # synthesize shared anthropic_model_sonnet before phase 4, which made them
    # impossible to repoint independently — and litellm-config.yaml already
    # defined a distinct alias for each. The provider credential setting is
    # deliberately gone: only the proxy holds provider keys now.
    parse_jd_model: str
    synthesize_model: str
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
        parse_jd_model=os.getenv("PARSE_JD_MODEL", "context-parse-jd"),
        synthesize_model=os.getenv("SYNTHESIZE_MODEL", "context-synthesize"),
        supabase_url=os.environ["SUPABASE_URL"],
        supabase_secret_key=os.environ["SUPABASE_SECRET_KEY"],
        cortex_mcp_url=os.environ["CORTEX_MCP_URL"],
        cortex_token_url=os.environ["CORTEX_TOKEN_URL"],
        internal_api_secret=os.environ["INTERNAL_API_SECRET"],
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_format=os.getenv("LOG_FORMAT", "json"),
    )
