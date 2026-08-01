"""CortexDebriefClient — async httpx proxy to the stateless Cortex debrief skill.

POSTs `{org_id, requisition_id, candidate_ids}` to
`{CORTEX_BACKEND_INTERNAL_URL}/api/v1/debrief` with the dedicated outbound
`X-Internal-Secret` (`CORTEX_INTERNAL_SECRET`, which must equal cortex-backend's
`INTERNAL_SECRET` — NOT the inbound slack-shared `INTERNAL_API_SECRET`) and
returns the parsed DebriefPacket dict.

Backend invariants honored:
  - No module-global loop-bound async client: a fresh `httpx.AsyncClient` is
    constructed PER ATTEMPT and closed in `finally` (this is a long-lived uvicorn
    process, but per-call construction sidesteps any loop-binding question and the
    retry loop needs clean state per attempt).
  - Bounded retry + backoff on 5xx / timeout / connect errors only; a 4xx is a
    deterministic caller error (bad org/req/candidate set) and is NOT retried.
  - Failure surfaces as the domain `UpstreamServiceError` (502) — never raw
    exception text in the caller-visible message.
  - No blocking I/O on the loop (`asyncio.sleep` for backoff, async httpx).
"""

from __future__ import annotations

import asyncio

import httpx
import structlog

from app.api.v2.core.exceptions import UpstreamServiceError
from app.config import get_settings

logger = structlog.get_logger(__name__)

_DEBRIEF_PATH = "/api/v1/debrief"


class CortexDebriefClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        internal_secret: str | None = None,
        max_retries: int = 3,
        base_backoff_s: float = 0.5,
        timeout_s: float = 30.0,
        connect_timeout_s: float = 5.0,
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.CORTEX_BACKEND_INTERNAL_URL).rstrip("/")
        # The OUTBOUND secret to cortex-backend is the DEDICATED CORTEX_INTERNAL_SECRET
        # (must equal cortex-backend's INTERNAL_SECRET) — NOT the inbound, slack-shared
        # INTERNAL_API_SECRET. The constructor override stays a test seam.
        self._secret = (
            internal_secret
            if internal_secret is not None
            else settings.CORTEX_INTERNAL_SECRET
        )
        self._max_retries = max(1, max_retries)
        self._base_backoff_s = base_backoff_s
        self._timeout = httpx.Timeout(timeout_s, connect=connect_timeout_s)

    async def generate(
        self, *, org_id: str, requisition_id: str, candidate_ids: list[str]
    ) -> dict:
        """Call the skill and return the parsed DebriefPacket dict.

        Retries 5xx / timeout / connect errors up to `max_retries` with linear
        backoff; raises UpstreamServiceError on exhaustion or a 4xx."""
        url = f"{self._base_url}{_DEBRIEF_PATH}"
        body = {
            "org_id": org_id,
            "requisition_id": requisition_id,
            "candidate_ids": candidate_ids,
        }
        headers = {
            "X-Internal-Secret": self._secret,
            "Content-Type": "application/json",
        }

        last_detail = "Debrief service unavailable"
        for attempt in range(1, self._max_retries + 1):
            client = httpx.AsyncClient(timeout=self._timeout)
            try:
                response = await client.post(url, json=body, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_detail = "Debrief service unreachable"
                logger.warning(
                    "cortex_debrief_transport_error",
                    error=str(exc),
                    attempt=attempt,
                )
                # transport errors are retryable
                await self._maybe_backoff(attempt)
                continue
            finally:
                try:
                    await client.aclose()
                except Exception as close_err:  # noqa: BLE001
                    logger.warning("cortex_debrief_client_close_failed", error=str(close_err))

            if response.status_code < 400:
                return response.json()

            if 400 <= response.status_code < 500:
                # Deterministic caller error — do not retry.
                logger.warning(
                    "cortex_debrief_4xx",
                    status=response.status_code,
                    attempt=attempt,
                )
                raise UpstreamServiceError("Debrief service rejected the request")

            # 5xx — retryable.
            last_detail = "Debrief service error"
            logger.warning(
                "cortex_debrief_5xx",
                status=response.status_code,
                attempt=attempt,
            )
            await self._maybe_backoff(attempt)

        raise UpstreamServiceError(last_detail)

    async def _maybe_backoff(self, attempt: int) -> None:
        """Linear backoff between attempts; no sleep after the final attempt."""
        if attempt < self._max_retries and self._base_backoff_s > 0:
            await asyncio.sleep(self._base_backoff_s * attempt)
