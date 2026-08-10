import asyncio
import time
from typing import Literal

import httpx

from src.config import get_settings
from src.logging import get_logger

logger = get_logger(__name__)


class LLMGatewayClient:
    # The LiteLLM gateway, not a provider. Provider choice lives in
    # litellm-config.yaml, so nothing in this module names one.
    PATH = "/v1/chat/completions"

    def __init__(self):
        self.settings = get_settings()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.settings.llm_gateway_url,
                timeout=httpx.Timeout(self.settings.llm_timeout),
                headers={
                    "authorization": f"Bearer {self.settings.litellm_master_key}",
                    "content-type": "application/json",
                },
            )
        return self._client

    async def call(
        self,
        prompt: str,
        model: Literal["haiku", "sonnet"] = "sonnet",
        max_tokens: int = 4096,
    ) -> str:
        client = await self._get_client()
        model_id = (
            self.settings.llm_model_haiku
            if model == "haiku"
            else self.settings.llm_model_sonnet
        )

        payload = {
            "model": model_id,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }

        last_exception = None
        for attempt in range(self.settings.llm_max_retries):
            try:
                logger.info(
                    "llm_request",
                    model=model_id,
                    prompt_len=len(prompt),
                    attempt=attempt + 1,
                )
                llm_start = time.monotonic()
                response = await client.post(self.PATH, json=payload)
                response.raise_for_status()

                resp_json = response.json()
                # OpenAI response shape. `content` can be null when the model
                # returns nothing, so it is coerced here rather than at each of
                # the ten call sites — every one of them does string work on the
                # result and would fail far from the cause.
                result = (resp_json["choices"][0]["message"].get("content") or "")
                usage = resp_json.get("usage", {})
                logger.info(
                    "llm_response",
                    model=model_id,
                    response_len=len(result),
                    duration_ms=int((time.monotonic() - llm_start) * 1000),
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                    cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                )
                return result

            except httpx.HTTPStatusError as e:
                last_exception = e
                if e.response.status_code == 429:
                    wait_time = 2 ** attempt
                    logger.warning(
                        "rate_limited",
                        attempt=attempt + 1,
                        wait_time=wait_time,
                    )
                    await asyncio.sleep(wait_time)
                elif e.response.status_code >= 500:
                    wait_time = 2 ** attempt
                    logger.warning(
                        "server_error",
                        status_code=e.response.status_code,
                        attempt=attempt + 1,
                        wait_time=wait_time,
                    )
                    await asyncio.sleep(wait_time)
                else:
                    raise

            except httpx.RequestError as e:
                last_exception = e
                wait_time = 2 ** attempt
                logger.warning(
                    "request_error",
                    error=str(e),
                    attempt=attempt + 1,
                    wait_time=wait_time,
                )
                await asyncio.sleep(wait_time)

        raise last_exception or Exception("Max retries exceeded")

    async def call_haiku(self, prompt: str, max_tokens: int = 1024) -> str:
        return await self.call(prompt, model="haiku", max_tokens=max_tokens)

    async def call_sonnet(self, prompt: str, max_tokens: int = 4096) -> str:
        return await self.call(prompt, model="sonnet", max_tokens=max_tokens)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


def _sync_call(prompt: str, model_alias: str, max_tokens: int, timeout: int) -> str:
    """One blocking gateway call. Shared by the two sync helpers below, which were
    byte-identical apart from alias, token budget and timeout — and each carried
    its own copy of the provider URL, headers and response-shape parsing."""
    settings = get_settings()
    if not settings.litellm_master_key:
        raise ValueError("LITELLM_MASTER_KEY not set")

    headers = {
        "authorization": f"Bearer {settings.litellm_master_key}",
        "content-type": "application/json",
    }
    payload = {
        "model": model_alias,
        "max_tokens": max_tokens,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }

    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{settings.llm_gateway_url}/v1/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"].get("content") or ""


def call_haiku_sync(prompt: str) -> str:
    settings = get_settings()
    return _sync_call(prompt, settings.llm_model_haiku, max_tokens=1024, timeout=60)


def call_sonnet_sync(prompt: str) -> str:
    settings = get_settings()
    return _sync_call(prompt, settings.llm_model_sonnet, max_tokens=4096, timeout=120)
