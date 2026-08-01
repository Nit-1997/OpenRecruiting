"""Single HTTP choke point for Knit calls.

Bounded retry (3 attempts) with exponential backoff + jitter, honoring
Retry-After on 429/5xx (CLAUDE.md external-API invariant). Maps HTTP failures
to the core ATS error taxonomy — nothing above this layer sees httpx errors.
"""

from __future__ import annotations

import asyncio
import json
import random

import httpx

from app.config import get_settings
from app.integrations.ats.core.errors import (
    AtsAuthError,
    AtsNotSupportedError,
    AtsProviderError,
    AtsRateLimitedError,
    AtsResourceNotFoundError,
)
from app.logging_config import get_logger

logger = get_logger(__name__)

_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.5
_TIMEOUT_SECONDS = 30.0
# Conservative markers for Knit's "tool not implemented for this app" 404s
# (e.g. ats.job.create on Workable). Anything else 404 = resource miss.
_NOT_SUPPORTED_MARKERS = ("not supported", "unsupported", "not available for")


def _retry_delay(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    return _BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.25)


def _error_msg(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error", {}).get("msg", ""))
    except Exception:
        return response.text[:200]


class KnitTransport:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        integration_id: str | None = None,
        params: dict | None = None,
        json: dict | None = None,
    ) -> dict:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if integration_id:
            headers["X-Knit-Integration-Id"] = integration_id
        url = f"{self._base_url}{path}"

        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = await self._client.request(
                    method, url, headers=headers, params=params, json=json
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "knit_network_error",
                    extra={
                        "event": "knit_network_error",
                        "path": path,
                        "attempt": attempt,
                        "error": str(exc),
                    },
                )
                if attempt < _MAX_ATTEMPTS - 1:
                    await asyncio.sleep(_retry_delay(attempt, None))
                continue

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < _MAX_ATTEMPTS - 1:
                    await asyncio.sleep(
                        _retry_delay(attempt, response.headers.get("Retry-After"))
                    )
                    continue
                if response.status_code == 429:
                    raise AtsRateLimitedError(_error_msg(response))
                raise AtsProviderError(
                    f"Knit {response.status_code} on {path}: {_error_msg(response)}"
                )

            return self._parse(response, path)

        raise AtsProviderError(f"Knit unreachable on {path}: {last_error}")

    async def passthrough(
        self, integration_id: str, method: str, path: str, body: dict | None = None
    ) -> dict:
        """Native passthrough to the connected provider's own API. The upstream
        response body comes back STRINGIFIED inside data.response.body."""
        envelope: dict = {"method": method, "path": path}
        if body is not None:
            envelope["body"] = body
        resp = await self.request(
            "POST", "/passthrough", integration_id=integration_id, json=envelope
        )
        inner = (resp.get("data") or {}).get("response") or {}
        raw = inner.get("body")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return {}
        return raw if isinstance(raw, dict) else {}

    def _parse(self, response: httpx.Response, path: str) -> dict:
        if response.status_code in (401, 403):
            raise AtsAuthError(f"Knit auth failure on {path}: {_error_msg(response)}")
        if response.status_code == 404:
            msg = _error_msg(response)
            lowered = msg.lower()
            if any(marker in lowered for marker in _NOT_SUPPORTED_MARKERS):
                raise AtsNotSupportedError(msg)
            raise AtsResourceNotFoundError(msg or path)
        if response.status_code >= 400:
            raise AtsProviderError(
                f"Knit {response.status_code} on {path}: {_error_msg(response)}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise AtsProviderError(f"Knit non-JSON response on {path}") from exc
        if isinstance(body, dict) and body.get("success") is False:
            raise AtsProviderError(
                f"Knit error on {path}: {_error_msg(response) or body}"
            )
        return body


_transport: KnitTransport | None = None


def get_knit_transport() -> KnitTransport:
    """Process-wide transport (long-running FastAPI service — NOT Lambda).
    Closed by aclose_knit_transport() from the app lifespan."""
    global _transport
    if _transport is None:
        settings = get_settings()
        _transport = KnitTransport(
            api_key=settings.KNIT_API_KEY,
            base_url=settings.KNIT_API_BASE_URL,
        )
    return _transport


async def aclose_knit_transport() -> None:
    global _transport
    if _transport is not None:
        try:
            await _transport.aclose()
        except Exception as exc:  # close failure must not mask shutdown
            logger.warning(
                "knit_transport_close_failed", extra={"error": str(exc)}
            )
        _transport = None
