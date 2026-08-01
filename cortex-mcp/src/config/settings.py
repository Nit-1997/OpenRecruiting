from functools import lru_cache
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../deploy-config/backend-deploy/env/.env-cortex-mcp",
        extra="ignore",
    )

    neo4j_uri: str
    # The backend .env names this NEO4J_USER; older configs may use
    # NEO4J_USERNAME. Accept either so a misnamed env var doesn't crashloop
    # the container.
    neo4j_username: str = Field(
        validation_alias=AliasChoices("NEO4J_USERNAME", "NEO4J_USER")
    )
    neo4j_password: str
    neo4j_database: str = "neo4j"

    oidc_issuer: str = "http://backend:8004"
    oidc_jwks_url: str = "http://backend:8004/.well-known/jwks.json"
    oidc_audience: str = "cortex-mcp"

    # Cortex-backend internal API — the only service holding both Neo4j +
    # Supabase, where the stateless debrief skill lives. `run_debrief` proxies
    # to its POST /api/v1/debrief endpoint, authenticated with the shared
    # X-Internal-Secret (same INTERNAL_SECRET the backends already use, so one
    # secret value works across services — do not fork it).
    cortex_backend_internal_url: str = "http://cortex-backend:8010"
    internal_secret: str = ""  # env: INTERNAL_SECRET (X-Internal-Secret header)
    debrief_timeout_seconds: float = 30.0  # the skill runs ~seconds (1 LLM pass)

    # External URL that MCP clients use to reach this server. Advertised
    # to clients in 401 responses + the protected-resource metadata
    # document so they can discover where to send tokens. Override with
    # the ngrok URL (or production URL) when fronting localhost.
    cortex_public_url: str = "http://localhost:8020"

    # Public-facing URL of the Scout authorization server. Clients fetch
    # /.well-known/oauth-authorization-server from this URL during OAuth
    # discovery. Defaults to the issuer for production; in dev with the
    # backend on a different ngrok URL set this explicitly.
    oidc_metadata_url: str = ""

    query_timeout_seconds: int = 10
    query_max_rows: int = 1000

    # Supabase — used by the audit log writer. Service-role key is required
    # because the audit table denies RLS reads/writes; we go in via the
    # service role. Aliased so the same `.env-fastapi` the backend uses
    # works here without duplicating secrets.
    supabase_url: str = ""
    supabase_secret_key: str = ""    # env: SUPABASE_SECRET_KEY (sb_secret_...)
    audit_enabled: bool = True
    audit_query_max_chars: int = 8000      # truncate huge queries before logging
    audit_error_max_chars: int = 500
    audit_timeout_seconds: float = 2.0     # fire-and-forget POST timeout

    # Rate limiter (in-memory token bucket per user / per org). Burst-friendly
    # short bursts allowed up to `*_burst`; sustained throughput governed by
    # `*_per_minute`. Counts every tool invocation, not just execute_query.
    rate_limit_user_per_minute: int = 60   # 1 req/sec sustained
    rate_limit_user_burst: int = 15
    rate_limit_org_per_minute: int = 600   # 10 req/sec across the org
    rate_limit_org_burst: int = 100
    rate_limit_enabled: bool = True

    log_level: str = "info"


@lru_cache
def get_settings() -> Settings:
    return Settings()
