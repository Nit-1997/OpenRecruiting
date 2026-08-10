from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: Literal["development", "staging", "production"] = "development"

    # The LiteLLM gateway. This worker no longer holds a provider credential:
    # LITELLM_MASTER_KEY authenticates it to the proxy, and the proxy holds the
    # provider keys. anthropic_api_key is gone entirely.
    llm_gateway_url: str = "http://litellm:4000"
    litellm_master_key: str = ""
    # GATEWAY ALIASES, not provider model ids. They preserve the tiers the two
    # call shapes used before phase 5 — feedback-haiku maps to haiku, and
    # feedback-sonnet to sonnet — so this migration does not silently re-price or
    # re-time either workload.
    llm_model_haiku: str = "feedback-haiku"
    llm_model_sonnet: str = "feedback-sonnet"
    llm_timeout: int = 120
    llm_max_retries: int = 3

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
