"""CortexInsightClient — async httpx proxy that forwards a confirmed recruiter
insight to cortex-backend's synchronous direct-ingest path.

POSTs an `IngestDirectRequest`-shaped body to
`{CORTEX_BACKEND_INTERNAL_URL}/ingest/direct` with the dedicated outbound
`X-Internal-Secret` (`CORTEX_INTERNAL_SECRET`, which must equal cortex-backend's
`INTERNAL_SECRET` — NOT the inbound `INTERNAL_API_SECRET`). The
`recruiter_insight` event-type is routed to `RecruiterInsightHandler.handle_direct`.

The cortex `IngestDirectRequest` model requires `event_type`, `org_id`,
`source_ref`, `timestamp`, and `payload` — so the full valid envelope is sent
(the spec's payload sketch is nested under `payload`).

Backend invariants (mirrors CortexDebriefClient):
  - No module-global loop-bound async client: a fresh `httpx.AsyncClient` is
    constructed PER ATTEMPT and closed in `finally`.
  - Bounded retry + backoff on 5xx / timeout / connect only, honoring a
    `Retry-After` header; a 4xx is a deterministic caller error, not retried.
  - Failure surfaces as the domain `UpstreamServiceError`; the SERVICE layer
    (DebriefInsightService) catches it so the recruiter's confirm never fails.
  - No blocking I/O on the loop (`asyncio.sleep` for backoff, async httpx).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import structlog

from app.api.v2.core.exceptions import UpstreamServiceError
from app.config import get_settings

logger = structlog.get_logger(__name__)

_INGEST_PATH = "/ingest/direct"
_EVENT_TYPE = "recruiter_insight"


class CortexInsightClient:
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
        self._secret = (
            internal_secret
            if internal_secret is not None
            else settings.CORTEX_INTERNAL_SECRET
        )
        self._max_retries = max(1, max_retries)
        self._base_backoff_s = base_backoff_s
        self._timeout = httpx.Timeout(timeout_s, connect=connect_timeout_s)

    async def ingest(
        self,
        *,
        org_id: str,
        requisition_id: str | None,
        candidate_id: str | None,
        kind: str,
        insight_text: str,
        triplet: dict | None = None,
    ) -> None:
        """Forward a confirmed recruiter insight to cortex-backend.

        Retries 5xx / timeout / connect up to `max_retries` (honoring
        `Retry-After`); raises UpstreamServiceError on exhaustion or a 4xx."""
        url = f"{self._base_url}{_INGEST_PATH}"
        payload = {
            "org_id": org_id,
            "requisition_id": requisition_id,
            "candidate_id": candidate_id,
            "kind": kind,
            "insight_text": insight_text,
            "triplet": triplet,
        }
        body = {
            "event_type": _EVENT_TYPE,
            "org_id": org_id,
            "source_ref": {
                "requisition_id": requisition_id,
                "candidate_id": candidate_id,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        headers = {
            "X-Internal-Secret": self._secret,
            "Content-Type": "application/json",
        }

        last_detail = "Insight service unavailable"
        for attempt in range(1, self._max_retries + 1):
            client = httpx.AsyncClient(timeout=self._timeout)
            retry_after: float | None = None
            try:
                response = await client.post(url, json=body, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_detail = "Insight service unreachable"
                logger.warning(
                    "cortex_insight_transport_error", error=str(exc), attempt=attempt
                )
                await self._maybe_backoff(attempt, None)
                continue
            finally:
                try:
                    await client.aclose()
                except Exception as close_err:  # noqa: BLE001
                    logger.warning(
                        "cortex_insight_client_close_failed", error=str(close_err)
                    )

            if response.status_code < 400:
                return

            if 400 <= response.status_code < 500:
                logger.warning(
                    "cortex_insight_4xx", status=response.status_code, attempt=attempt
                )
                raise UpstreamServiceError("Insight service rejected the request")

            last_detail = "Insight service error"
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            logger.warning(
                "cortex_insight_5xx", status=response.status_code, attempt=attempt
            )
            await self._maybe_backoff(attempt, retry_after)

        raise UpstreamServiceError(last_detail)

    async def _maybe_backoff(self, attempt: int, retry_after: float | None) -> None:
        """Backoff between attempts; honor Retry-After when present. No sleep
        after the final attempt."""
        if attempt >= self._max_retries:
            return
        if retry_after is not None:
            await asyncio.sleep(retry_after)
        elif self._base_backoff_s > 0:
            await asyncio.sleep(self._base_backoff_s * attempt)


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a numeric Retry-After header (seconds). Ignore HTTP-date forms and
    malformed values — they fall back to linear backoff."""
    if not value:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None
