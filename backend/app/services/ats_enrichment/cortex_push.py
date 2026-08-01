"""Best-effort push of an enriched candidate profile to cortex-backend's
synchronous direct-ingest path (`{CORTEX_BACKEND_INTERNAL_URL}/ingest/direct`,
`X-Internal-Secret` = CORTEX_INTERNAL_SECRET — same envelope as CortexInsightClient,
routed to the `candidate_profile_enriched` handler).

This is the LAST step of enrichment and is strictly best-effort: a cortex outage
must never fail the enrichment (the profile is already persisted on the candidate).
So it returns a bool and never raises. Fresh httpx client per attempt, closed in
finally (no loop-bound module global)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)

_INGEST_PATH = "/api/v1/ingest/direct"
_MAX_ATTEMPTS = 2


async def _push_event(
    event_type: str,
    org_id: str,
    candidate_id: str,
    payload: dict,
    base_url: str | None = None,
    secret: str | None = None,
) -> bool:
    settings = get_settings()
    url = f"{(base_url or settings.CORTEX_BACKEND_INTERNAL_URL).rstrip('/')}{_INGEST_PATH}"
    body = {
        "event_type": event_type,
        "org_id": org_id,
        "source_ref": {"candidate_id": candidate_id},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    headers = {
        "X-Internal-Secret": secret if secret is not None else settings.CORTEX_INTERNAL_SECRET,
        "Content-Type": "application/json",
    }
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        # Graphiti add_triplet writes one edge at a time to Neo4j, so a full
        # profile (20-30 triplets) routinely takes well over 20s. Give the read
        # a generous budget — a too-short timeout makes us log false failures and
        # retry, double-ingesting (idempotent, but wasteful).
        client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0))
        try:
            response = await client.post(url, json=body, headers=headers)
            if response.status_code < 400:
                return True
            if 400 <= response.status_code < 500:
                logger.warning("cortex_push_4xx", status=response.status_code)
                return False
            logger.warning("cortex_push_5xx", status=response.status_code, attempt=attempt)
        except Exception as exc:  # noqa: BLE001 — best-effort, never fail enrichment
            logger.warning("cortex_push_failed", error=str(exc), attempt=attempt)
        finally:
            try:
                await client.aclose()
            except Exception as close_err:  # noqa: BLE001
                logger.warning("cortex_push_close_failed", error=str(close_err))
        if attempt < _MAX_ATTEMPTS:
            await asyncio.sleep(0.5)
    return False


async def push_candidate_profile(
    *,
    org_id: str,
    candidate_id: str,
    payload: dict,
    base_url: str | None = None,
    secret: str | None = None,
) -> bool:
    return await _push_event(
        "candidate_profile_enriched", org_id, candidate_id, payload, base_url, secret
    )


async def push_candidate_evaluation(
    *,
    org_id: str,
    candidate_id: str,
    payload: dict,
    base_url: str | None = None,
    secret: str | None = None,
) -> bool:
    return await _push_event(
        "candidate_evaluation", org_id, candidate_id, payload, base_url, secret
    )
