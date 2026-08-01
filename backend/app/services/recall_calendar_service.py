"""
Recall.ai Calendar V2 API wrapper for v2.

DELIBERATE DUPLICATION: ported from backend/v1/app/services/recall_calendar_service.py.
v2 must be standalone so v1 can be decommissioned cleanly. Keep in lockstep when either
changes. Long-term fix: extract to backend/shared/services/.
"""

import asyncio
import httpx
import json
import random
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional
from app.config import get_settings
from app.logging_config import get_logger
from app.services.supabase import get_supabase_admin_client

logger = get_logger(__name__)

# Bounded exponential-backoff policy (shared by Recall calendar calls).
RETRY_MAX_ATTEMPTS = 4          # 1 initial try + 3 retries
RETRY_BASE_SECONDS = 0.5        # base for exponential growth
RETRY_MAX_BACKOFF_SECONDS = 30.0
RETRY_JITTER_SECONDS = 0.25     # +/- jitter to avoid thundering herd


def _is_retryable_status(status_code: int) -> bool:
    """Retry only on rate-limit (429) and server errors (5xx).
    Other 4xx (401/403/400/404) are hard failures — fail fast."""
    return status_code == 429 or 500 <= status_code <= 599


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    """Parse a Retry-After header (integer seconds form only)."""
    raw = response.headers.get("Retry-After") if response is not None else None
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def _backoff_delay(attempt: int, response: Optional[httpx.Response]) -> float:
    """Delay before the next attempt (0-indexed attempt). Honors Retry-After
    when present, otherwise exponential backoff with jitter, capped."""
    server_hint = _retry_after_seconds(response) if response is not None else None
    if server_hint is not None:
        return min(server_hint, RETRY_MAX_BACKOFF_SECONDS)
    exp = RETRY_BASE_SECONDS * (2 ** attempt)
    jitter = random.uniform(0.0, RETRY_JITTER_SECONDS)
    return min(exp + jitter, RETRY_MAX_BACKOFF_SECONDS)


async def _send_with_backoff(
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    label: str,
) -> httpx.Response:
    """Invoke `send()` with bounded exponential backoff, retrying ONLY on
    429/5xx. Returns the final response (which may still be an error status —
    callers handle non-retryable / exhausted cases). asyncio.sleep is the only
    blocking point, so tests can mock it for determinism."""
    response: Optional[httpx.Response] = None
    for attempt in range(RETRY_MAX_ATTEMPTS):
        response = await send()
        if not _is_retryable_status(response.status_code):
            return response
        if attempt == RETRY_MAX_ATTEMPTS - 1:
            logger.warning(
                f"Recall Calendar V2 {label}: retries exhausted "
                f"status={response.status_code} attempts={RETRY_MAX_ATTEMPTS}"
            )
            return response
        delay = _backoff_delay(attempt, response)
        logger.warning(
            f"Recall Calendar V2 {label}: retryable status={response.status_code} "
            f"attempt={attempt + 1}/{RETRY_MAX_ATTEMPTS} backoff={delay:.2f}s"
        )
        await asyncio.sleep(delay)
    return response


def _extract_disallowed_bot_config_fields(error_body: str) -> set[str]:
    if not error_body:
        return set()

    disallowed: set[str] = set()
    try:
        parsed = json.loads(error_body)
    except Exception:
        parsed = None

    errors = parsed.get("errors") if isinstance(parsed, dict) else None
    if isinstance(errors, dict):
        for field_name, messages in errors.items():
            if isinstance(messages, list):
                message_list = [str(msg) for msg in messages]
            else:
                message_list = [str(messages)]

            if any("not allowed" in msg.lower() for msg in message_list):
                key = str(field_name).split(".")[-1].strip()
                if key:
                    disallowed.add(key)

    # Fallback for truncated/non-JSON logs that still mention rejected fields.
    lowered = error_body.lower()
    if "recording_mode" in lowered and "not allowed" in lowered:
        disallowed.add("recording_mode")

    return disallowed


def _without_disallowed_bot_config_fields(payload: dict, disallowed_fields: set[str]) -> Optional[dict]:
    if not disallowed_fields:
        return None
    if not isinstance(payload, dict):
        return None

    bot_config = payload.get("bot_config")
    if not isinstance(bot_config, dict):
        return None

    next_payload = dict(payload)
    next_bot_config = dict(bot_config)
    removed_any = False

    for field in disallowed_fields:
        if field in next_bot_config:
            next_bot_config.pop(field, None)
            removed_any = True

    if not removed_any:
        return None

    next_payload["bot_config"] = next_bot_config
    return next_payload


class RecallCalendarServiceError(Exception):
    def __init__(self, message: str, status_code: int = None, details: dict = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class RecallCalendarService:
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.RECALL_API_KEY
        v1_base = settings.RECALL_BASE_URL
        self.base_url = v1_base.replace("/api/v1", "/api/v2")
        self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Token {self.api_key}"},
                timeout=30.0,
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def register_calendar(
        self, profile_id: str, org_id: str, refresh_token: str, provider_email: str
    ) -> Optional[str]:
        try:
            payload = {
                "platform": "google_calendar",
                "oauth_client_id": get_settings().GOOGLE_CLIENT_ID,
                "oauth_client_secret": get_settings().GOOGLE_CLIENT_SECRET,
                "oauth_refresh_token": refresh_token,
            }
            resp = await self.client.post("/calendars/", json=payload)

            if resp.status_code == 429:
                logger.warning(f"Recall Calendar V2 rate limited during register for profile={profile_id}")
                return None

            if resp.status_code >= 400:
                logger.error(
                    f"Recall Calendar V2 register failed: status={resp.status_code} "
                    f"body={resp.text[:200]} profile={profile_id}"
                )
                return None

            data = resp.json()
            recall_calendar_id = data.get("id")
            if not recall_calendar_id:
                logger.error(f"Recall Calendar V2 register returned no id: {data}")
                return None

            supabase = get_supabase_admin_client()
            await supabase.table("user_connections") \
                .update({"recall_calendar_id": str(recall_calendar_id)}) \
                .eq("profile_id", profile_id) \
                .eq("provider", "google_calendar") \
                .eq("is_active", True) \
                .execute_async()

            logger.info(
                f"Calendar registered with Recall V2: profile={profile_id} "
                f"recall_calendar_id={recall_calendar_id} email={provider_email}"
            )
            return str(recall_calendar_id)

        except Exception as e:
            logger.error(f"Recall Calendar V2 register exception: {e} profile={profile_id}")
            return None

    async def poll_events(self, since: datetime) -> tuple[list[dict], bool]:
        """Returns (events, complete). complete=False means poll was partial — do NOT advance checkpoint.

        A single httpx.AsyncClient (self.client) is reused across ALL pages,
        including absolute `next` URLs — no per-page client construction.
        Each page request retries on 429/5xx with bounded exponential backoff."""
        from urllib.parse import urlparse, parse_qs

        all_events = []
        next_request_params = {
            "updated_at__gte": since.isoformat(),
            "limit": 100,
        }
        max_pages = 50
        next_url = None

        try:
            for _ in range(max_pages):
                resp = await _send_with_backoff(
                    lambda: self.client.get("/calendar-events/", params=next_request_params),
                    label="poll",
                )

                if resp.status_code >= 400:
                    if resp.status_code == 429:
                        logger.warning("Recall Calendar V2 poll rate limited after retries")
                    else:
                        logger.error(
                            f"Recall Calendar V2 poll failed: status={resp.status_code} "
                            f"body={resp.text[:200]}"
                        )
                    return all_events, False

                data = resp.json()
                results = data.get("results", [])
                all_events.extend(results)

                next_url = data.get("next")
                if not next_url or not results:
                    break

                # Reuse the same client for the next page; only the cursor/query
                # params change. Absolute `next` URLs share the same host as
                # base_url, so we extract the query and keep the relative path.
                next_request_params = {k: v[0] for k, v in parse_qs(urlparse(next_url).query).items()}

            else:
                if next_url:
                    logger.warning(f"Recall Calendar V2 poll: hit {max_pages} page cap with more pages remaining")
                    return all_events, False

        except Exception as e:
            logger.error(f"Recall Calendar V2 poll exception: {e}")
            return all_events, False

        return all_events, True

    async def deploy_calendar_bot(self, recall_event_id: str, bot_config: dict) -> Optional[dict]:
        try:
            payload = bot_config if isinstance(bot_config, dict) else {}
            resp = await self.client.post(
                f"/calendar-events/{recall_event_id}/bot/",
                json=payload,
            )

            if resp.status_code == 400:
                disallowed_fields = _extract_disallowed_bot_config_fields(resp.text or "")
                retry_payload = _without_disallowed_bot_config_fields(payload, disallowed_fields)
                if retry_payload is not None:
                    logger.warning(
                        "Recall Calendar V2 deploy_bot rejected bot_config fields="
                        f"{sorted(disallowed_fields)} event={recall_event_id}; retrying without them"
                    )
                    resp = await self.client.post(
                        f"/calendar-events/{recall_event_id}/bot/",
                        json=retry_payload,
                    )

            if resp.status_code == 429:
                logger.warning(f"Recall Calendar V2 deploy_bot rate limited for event={recall_event_id}")
                return None

            if resp.status_code >= 400:
                logger.error(
                    f"Recall Calendar V2 deploy_bot failed: status={resp.status_code} "
                    f"body={resp.text[:200]} event={recall_event_id}"
                )
                return None

            return resp.json()

        except Exception as e:
            logger.error(f"Recall Calendar V2 deploy_bot exception: {e} event={recall_event_id}")
            return None

    async def remove_calendar_bot(self, recall_event_id: str) -> bool:
        try:
            resp = await self.client.delete(f"/calendar-events/{recall_event_id}/bot/")

            if resp.status_code in (200, 204):
                logger.info(f"Recall Calendar V2 bot removed for event={recall_event_id}")
                return True

            logger.error(
                f"Recall Calendar V2 remove_bot failed: status={resp.status_code} "
                f"body={resp.text[:200]} event={recall_event_id}"
            )
            return False

        except Exception as e:
            logger.error(f"Recall Calendar V2 remove_bot exception: {e} event={recall_event_id}")
            return False

    async def get_calendar_status(self, recall_calendar_id: str) -> Optional[dict]:
        try:
            resp = await self.client.get(f"/calendars/{recall_calendar_id}/")

            if resp.status_code >= 400:
                logger.error(
                    f"Recall Calendar V2 get_status failed: status={resp.status_code} "
                    f"calendar={recall_calendar_id}"
                )
                return None

            return resp.json()

        except Exception as e:
            logger.error(f"Recall Calendar V2 get_status exception: {e} calendar={recall_calendar_id}")
            return None


def get_recall_calendar_service() -> RecallCalendarService:
    return RecallCalendarService()
