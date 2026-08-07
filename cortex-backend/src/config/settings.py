import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel


class AppConfig(BaseModel):
    name: str = "cortex"
    version: str = "0.1.0"
    description: str = ""


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8010
    workers: int = 2


class Neo4jConfig(BaseModel):
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "cortex_dev_2026"
    database: str = "neo4j"
    max_connection_pool_size: int = 50
    connection_acquisition_timeout: int = 60


class SupabaseConfig(BaseModel):
    url: str = ""
    service_role_key: str = ""


class OpenAIConfig(BaseModel):
    api_key: str = ""


class AuthConfig(BaseModel):
    internal_secret: str = ""


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "json"
    correlation_id: bool = True


class CorsConfig(BaseModel):
    allowed_origins: list[str] = ["*"]
    allowed_methods: list[str] = ["GET", "POST", "PUT", "DELETE"]
    allowed_headers: list[str] = ["*"]


class SyncConfig(BaseModel):
    enabled: bool = True
    # Eligibility is gated by settledness_window_hours, not by how often we look:
    # polling daily would leave a newly settled row waiting another full day.
    poll_interval_seconds: int = 60
    reconciliation_interval_days: int = 7
    settledness_window_hours: int = 48
    publish_batch_size: int = 1000
    claim_lease_seconds: int = 300
    claim_batch_size: int = 10
    claim_max_attempts: int = 5


class Settings(BaseModel):
    app: AppConfig = AppConfig()
    server: ServerConfig = ServerConfig()
    neo4j: Neo4jConfig = Neo4jConfig()
    supabase: SupabaseConfig = SupabaseConfig()
    openai: OpenAIConfig = OpenAIConfig()
    auth: AuthConfig = AuthConfig()
    logging: LoggingConfig = LoggingConfig()
    cors: CorsConfig = CorsConfig()
    sync: SyncConfig = SyncConfig()


@lru_cache()
def get_settings() -> Settings:
    config_path = Path(__file__).parent.parent.parent / "application.yaml"
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f)
        settings = Settings(**raw)
    else:
        settings = Settings()

    if neo4j_uri := os.environ.get("NEO4J_URI"):
        settings.neo4j.uri = neo4j_uri
    if neo4j_user := os.environ.get("NEO4J_USER"):
        settings.neo4j.user = neo4j_user
    if neo4j_password := os.environ.get("NEO4J_PASSWORD"):
        settings.neo4j.password = neo4j_password
    if neo4j_database := os.environ.get("NEO4J_DATABASE"):
        settings.neo4j.database = neo4j_database
    if log_level := os.environ.get("LOG_LEVEL"):
        settings.logging.level = log_level
    if supabase_url := os.environ.get("SUPABASE_URL"):
        settings.supabase.url = supabase_url
    # SUPABASE_SECRET_KEY (sb_secret_...) is what the rest of the stack ships in
    # .env; reading only the older name left every Supabase call unauthenticated.
    if supabase_key := (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SECRET_KEY")
    ):
        settings.supabase.service_role_key = supabase_key
    if openai_key := os.environ.get("OPENAI_API_KEY"):
        settings.openai.api_key = openai_key
    if internal_secret := os.environ.get("INTERNAL_SECRET"):
        settings.auth.internal_secret = internal_secret
    if sync_enabled := os.environ.get("CORTEX_SYNC_ENABLED"):
        settings.sync.enabled = sync_enabled.lower() in ("1", "true", "yes")

    return settings
