from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../deploy-config/backend-deploy/env/.env-voice-agent",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_url: str = ""
    supabase_secret_key: str = ""

    recall_api_key: str = ""
    recall_base_url: str = "https://us-west-2.recall.ai/api/v1"

    voice_deepgram_api_key: str = ""
    voice_anthropic_api_key: str = ""
    voice_anthropic_model: str = "claude-sonnet-4-5-20250929"
    voice_tts_voice: str = "aura-2-helena-en"

    max_context_tokens: int = 8000
    target_context_tokens: int = 6000
    max_unsummarized_messages: int = 20
    min_messages_after_summary: int = 4
    flux_eot_threshold: float = 0.75
    flux_eager_eot_threshold: float | None = None
    flux_eot_timeout_ms: int | None = 3000

    ice_stun_servers: list = ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]
    turn_server_url: str = ""
    turn_username: str = ""
    turn_credential: str = ""

    # Backend internal API (called when feedback voice session completes).
    # On EC2 with host networking, default localhost is correct.
    # On macOS dev (bridge mode), set BACKEND_URL=http://backend:8004.
    backend_url: str = "http://localhost:8004"
    internal_api_secret: str = ""

    # v2-specific settings
    service_port: int = 8011  # default differs from v1 (8001)
    anthropic_model_sonnet: str = "claude-sonnet-4-6"
    intake_v2_voice_session_timeout_secs: int = 1800  # 30 minutes for intake


@lru_cache
def get_settings() -> Settings:
    return Settings()
