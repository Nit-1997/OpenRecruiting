from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: Literal["development", "staging", "production"] = "development"

    anthropic_api_key: str = ""
    anthropic_model_haiku: str = "claude-haiku-4-5-20251001"
    anthropic_model_sonnet: str = "claude-sonnet-4-6"
    anthropic_timeout: int = 120
    anthropic_max_retries: int = 3

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str | None = None

    max_parallel_llm_calls: int = 10

    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "text"

    api_port: int = 8001

    supabase_url: str = ""
    supabase_secret_key: str = ""

    recall_api_key: str = ""
    recall_base_url: str = "https://api.recall.ai/api/v1"

    backend_url: str = ""
    lambda_callback_secret: str = ""

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
