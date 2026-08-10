from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: Literal["development", "staging", "production"] = "development"

    # The LiteLLM gateway. This worker holds no provider credential:
    # LITELLM_MASTER_KEY authenticates it to the proxy, which holds the keys.
    llm_gateway_url: str = "http://litellm:4000"
    litellm_master_key: str = ""
    # GATEWAY ALIASES, not provider model ids, preserving each shape's tier.
    # NOTE: intake-agent-haiku currently has NO CALLER — call_haiku is unused in
    # this worker. The alias is kept rather than deleted so the symmetry with
    # call_sonnet survives; see the client docstring.
    llm_model_haiku: str = "intake-agent-haiku"
    llm_model_sonnet: str = "intake-agent-sonnet"
    llm_timeout: int = 120
    llm_max_retries: int = 3

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
