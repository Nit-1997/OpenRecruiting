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

    supabase_url: str = ""
    supabase_secret_key: str = ""

    sqs_queue_url: str = ""
    sqs_region: str = "us-west-1"

    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "text"

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
