"""
Google Calendar integration service for v2.

DELIBERATE DUPLICATION: ported from backend/v1/app/services/google_calendar_service.py.
v2 cannot import from v1 (separate FastAPI process, separate sys.path). Keep in lockstep
when either changes. Long-term fix: extract to backend/shared/services/.

Differences from v1:
- Imports use v2 module paths
- backfill_recall_registrations removed (admin utility, not needed in v2 routers)
- register_with_recall returns False when CALENDAR_INTELLIGENCE_ENABLED=False
"""

import asyncio
import json
import random
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Awaitable, Callable, Optional
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.logging_config import get_logger
from app.services.supabase import get_async_http_client, get_supabase_admin_client
from app.utils import parse_iso_datetime

logger = get_logger(__name__)

# Bounded exponential-backoff policy for Google API calls.
RETRY_MAX_ATTEMPTS = 4          # 1 initial try + 3 retries
RETRY_BASE_SECONDS = 0.5        # base for exponential growth
RETRY_MAX_BACKOFF_SECONDS = 30.0
RETRY_JITTER_SECONDS = 0.25     # +/- jitter to avoid thundering herd


def _is_retryable_status(status_code: int) -> bool:
    """Retry only on rate-limit (429) and server errors (5xx).
    Auth/client errors (401/403/400/404) are hard failures — fail fast."""
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
    """Delay before the next attempt (0-indexed). Honors Retry-After when
    present, else exponential backoff with jitter, capped."""
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
    429/5xx (never on 4xx auth errors). Returns the final response; callers
    still inspect status_code and raise their own ValueError on failure.
    asyncio.sleep is the only blocking point so tests mock it for determinism."""
    response: Optional[httpx.Response] = None
    for attempt in range(RETRY_MAX_ATTEMPTS):
        response = await send()
        if not _is_retryable_status(response.status_code):
            return response
        if attempt == RETRY_MAX_ATTEMPTS - 1:
            logger.warning(
                f"Google {label}: retries exhausted "
                f"status={response.status_code} attempts={RETRY_MAX_ATTEMPTS}"
            )
            return response
        delay = _backoff_delay(attempt, response)
        logger.warning(
            f"Google {label}: retryable status={response.status_code} "
            f"attempt={attempt + 1}/{RETRY_MAX_ATTEMPTS} backoff={delay:.2f}s"
        )
        await asyncio.sleep(delay)
    return response


def _strip_offset(dt_str: str) -> str:
    """Strip UTC offset so Google Calendar uses the IANA timeZone field instead."""
    return re.sub(r'([+-]\d{2}:\d{2}|Z)$', '', dt_str)


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_SCOPES = (
    "openid email "
    "https://www.googleapis.com/auth/calendar.readonly "
    "https://www.googleapis.com/auth/calendar.events"
)


class GoogleCalendarService:
    def __init__(self):
        settings = get_settings()
        key = settings.INTEGRATION_ENCRYPTION_KEY
        self._fernet = Fernet(key.encode()) if key else None

    def encrypt_token(self, token: str) -> str:
        if not self._fernet:
            raise RuntimeError("INTEGRATION_ENCRYPTION_KEY not configured")
        return self._fernet.encrypt(token.encode()).decode()

    def decrypt_token(self, encrypted: str) -> str:
        if not self._fernet:
            raise RuntimeError("INTEGRATION_ENCRYPTION_KEY not configured")
        return self._fernet.decrypt(encrypted.encode()).decode()

    def create_oauth_state(self, user_id: str, org_id: str) -> str:
        if not self._fernet:
            raise RuntimeError("INTEGRATION_ENCRYPTION_KEY not configured")
        payload = json.dumps({
            "user_id": user_id,
            "org_id": org_id,
            "exp": int(time.time()) + 600,
        })
        return self._fernet.encrypt(payload.encode()).decode()

    def verify_oauth_state(self, state: str) -> dict:
        if not self._fernet:
            raise RuntimeError("INTEGRATION_ENCRYPTION_KEY not configured")
        try:
            decrypted = self._fernet.decrypt(state.encode()).decode()
            data = json.loads(decrypted)
            if data.get("exp", 0) < time.time():
                raise ValueError("OAuth state expired")
            return data
        except InvalidToken:
            raise ValueError("Invalid OAuth state")

    def build_oauth_url(self, state: str) -> str:
        settings = get_settings()
        params = urlencode({
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": GOOGLE_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })
        return f"{GOOGLE_AUTH_URL}?{params}"

    async def exchange_code(self, code: str) -> dict:
        settings = get_settings()
        client = get_async_http_client()
        resp = await _send_with_backoff(
            lambda: client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            ),
            label="oauth_exchange",
        )
        data = resp.json()
        if resp.status_code != 200:
            logger.error(f"Google OAuth exchange failed: {data.get('error_description', data.get('error'))}")
            raise ValueError(f"Google OAuth failed: {data.get('error_description', data.get('error'))}")
        return data

    async def get_userinfo(self, access_token: str) -> dict:
        client = get_async_http_client()
        resp = await _send_with_backoff(
            lambda: client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            ),
            label="userinfo",
        )
        if resp.status_code != 200:
            raise ValueError("Failed to fetch Google user info")
        return resp.json()

    async def _refresh_token(self, refresh_token_encrypted: str) -> dict:
        settings = get_settings()
        client = get_async_http_client()
        refresh_token = self.decrypt_token(refresh_token_encrypted)
        resp = await _send_with_backoff(
            lambda: client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            ),
            label="token_refresh",
        )
        data = resp.json()
        if resp.status_code != 200:
            logger.error(f"Google token refresh failed: {data.get('error_description', data.get('error'))}")
            raise ValueError("Failed to refresh Google token")
        return data

    async def _get_valid_token(self, profile_id: str) -> str:
        connection = await self.get_connection(profile_id)
        if not connection:
            raise ValueError("Google Calendar not connected")

        expires_at = connection.get("token_expires_at")
        if expires_at:
            exp_dt = parse_iso_datetime(expires_at)
            if exp_dt > datetime.now(timezone.utc) + timedelta(minutes=2):
                return self.decrypt_token(connection["access_token_encrypted"])

        token_data = await self._refresh_token(connection["refresh_token_encrypted"])
        new_access = token_data["access_token"]
        new_expires = datetime.now(timezone.utc) + timedelta(seconds=token_data.get("expires_in", 3600))

        supabase = get_supabase_admin_client()
        update: dict = {
            "access_token_encrypted": self.encrypt_token(new_access),
            "token_expires_at": new_expires.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if token_data.get("refresh_token"):
            update["refresh_token_encrypted"] = self.encrypt_token(token_data["refresh_token"])

        await supabase.table("user_connections") \
            .update(update) \
            .eq("id", connection["id"]) \
            .execute_async()

        return new_access

    async def get_connection(self, profile_id: str) -> dict | None:
        supabase = get_supabase_admin_client()
        result = await supabase.table("user_connections") \
            .select("*") \
            .eq("profile_id", profile_id) \
            .eq("provider", "google_calendar") \
            .eq("is_active", True) \
            .limit(1) \
            .execute_async()
        return result.data[0] if result.data else None

    async def save_connection(self, profile_id: str, org_id: str, tokens: dict, email: str) -> None:
        supabase = get_supabase_admin_client()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))

        existing = await supabase.table("user_connections") \
            .select("id, recall_calendar_id") \
            .eq("profile_id", profile_id) \
            .eq("provider", "google_calendar") \
            .limit(1) \
            .execute_async()

        row: dict = {
            "profile_id": profile_id,
            "organization_id": org_id,
            "provider": "google_calendar",
            "provider_email": email,
            "access_token_encrypted": self.encrypt_token(tokens["access_token"]),
            "refresh_token_encrypted": self.encrypt_token(tokens["refresh_token"]),
            "token_expires_at": expires_at.isoformat(),
            "scopes": tokens.get("scope", GOOGLE_SCOPES),
            "is_active": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        self._prior_recall_calendar_id = None
        if existing.data:
            self._prior_recall_calendar_id = existing.data[0].get("recall_calendar_id")
            if get_settings().CALENDAR_INTELLIGENCE_ENABLED:
                row["recall_calendar_id"] = None
            await supabase.table("user_connections") \
                .update(row) \
                .eq("id", existing.data[0]["id"]) \
                .execute_async()
        else:
            await supabase.table("user_connections") \
                .insert(row) \
                .execute_async()

    async def register_with_recall(self, profile_id: str, org_id: str) -> bool:
        if not get_settings().CALENDAR_INTELLIGENCE_ENABLED:
            return False

        try:
            supabase = get_supabase_admin_client()
            conn = await supabase.table("user_connections") \
                .select("refresh_token_encrypted, provider_email") \
                .eq("profile_id", profile_id) \
                .eq("provider", "google_calendar") \
                .eq("is_active", True) \
                .execute_async()

            if not conn.data:
                logger.warning(f"Calendar register_with_recall: no connection for profile={profile_id}")
                return False

            refresh_token = self.decrypt_token(conn.data[0]["refresh_token_encrypted"])
            provider_email = conn.data[0].get("provider_email", "")

            from app.services.recall_calendar_service import get_recall_calendar_service
            recall_cal = get_recall_calendar_service()
            try:
                recall_calendar_id = await recall_cal.register_calendar(
                    profile_id=profile_id,
                    org_id=org_id,
                    refresh_token=refresh_token,
                    provider_email=provider_email,
                )
            finally:
                await recall_cal.close()

            if recall_calendar_id:
                logger.info(f"Calendar register_with_recall: success profile={profile_id} recall_cal_id={recall_calendar_id}")
                return True
            else:
                logger.warning(f"Calendar register_with_recall: failed for profile={profile_id}")
                await self._restore_prior_recall_id(profile_id, supabase)
                return False

        except Exception as e:
            logger.error(f"Calendar register_with_recall exception: {e} profile={profile_id}")
            supabase = get_supabase_admin_client()
            await self._restore_prior_recall_id(profile_id, supabase)
            return False

    async def _restore_prior_recall_id(self, profile_id: str, supabase) -> None:
        prior_id = getattr(self, "_prior_recall_calendar_id", None)
        if prior_id:
            await supabase.table("user_connections") \
                .update({"recall_calendar_id": prior_id}) \
                .eq("profile_id", profile_id) \
                .eq("provider", "google_calendar") \
                .eq("is_active", True) \
                .execute_async()
            logger.info(f"Calendar register_with_recall: restored prior recall_calendar_id={prior_id} for profile={profile_id}")

    async def disconnect(self, profile_id: str) -> dict:
        supabase = get_supabase_admin_client()

        try:
            conn = await supabase.table("user_connections") \
                .select("recall_calendar_id") \
                .eq("profile_id", profile_id) \
                .eq("provider", "google_calendar") \
                .eq("is_active", True) \
                .execute_async()
        except Exception as e:
            logger.error(f"Calendar disconnect: failed to read connection for profile={profile_id}: {e}")
            raise RuntimeError("Unable to verify connection before disconnect") from e

        recall_cal_id = conn.data[0].get("recall_calendar_id") if conn.data else None

        recall_deregistered = False
        if recall_cal_id:
            recall_cal = None
            try:
                from app.services.recall_calendar_service import get_recall_calendar_service
                recall_cal = get_recall_calendar_service()
                resp = await recall_cal.client.delete(f"/calendars/{recall_cal_id}/")
                if resp.status_code in (200, 204):
                    logger.info(f"Calendar disconnect: deregistered Recall calendar {recall_cal_id}")
                    recall_deregistered = True
                else:
                    logger.error(f"Calendar disconnect: Recall deregister failed status={resp.status_code}")
                    raise RuntimeError(f"Recall deregistration failed for calendar={recall_cal_id} status={resp.status_code}")
            except Exception as e:
                logger.error(f"Calendar disconnect: Recall deregister exception: {e}")
                raise RuntimeError("Recall deregistration failed; disconnect aborted") from e
            finally:
                if recall_cal:
                    try:
                        await recall_cal.close()
                    except Exception as close_err:
                        logger.warning(f"Calendar disconnect: recall client close failed: {close_err}")

        await supabase.table("user_connections") \
            .update({
                "is_active": False,
                "calendar_watch_enabled": False,
                "recall_calendar_id": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }) \
            .eq("profile_id", profile_id) \
            .eq("provider", "google_calendar") \
            .eq("is_active", True) \
            .execute_async()

        return {"disconnected": True, "recall_deregistered": recall_deregistered}

    async def find_available_slots(
        self,
        profile_id: str,
        start_date: str,
        end_date: str,
        duration_minutes: int = 30,
        timezone_name: str | None = None,
        start_hour: int = 9,
        end_hour: int = 17,
    ) -> dict:
        if not timezone_name:
            supabase = get_supabase_admin_client()
            profile = await supabase.table("profiles") \
                .select("timezone") \
                .eq("id", profile_id) \
                .single() \
                .execute_async()
            timezone_name = (profile.data or {}).get("timezone") or "UTC"

        tz = ZoneInfo(timezone_name)
        access_token = await self._get_valid_token(profile_id)
        client = get_async_http_client()

        time_min = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=tz, hour=0, minute=0)
        time_max = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=tz, hour=23, minute=59, second=59)

        resp = await _send_with_backoff(
            lambda: client.post(
                f"{GOOGLE_CALENDAR_API}/freeBusy",
                json={
                    "timeMin": time_min.isoformat(),
                    "timeMax": time_max.isoformat(),
                    "timeZone": timezone_name,
                    "items": [{"id": "primary"}],
                },
                headers={"Authorization": f"Bearer {access_token}"},
            ),
            label="freeBusy",
        )

        if resp.status_code != 200:
            logger.error(f"Google freeBusy failed: {resp.text}")
            raise ValueError("Failed to fetch calendar availability")

        busy_periods = resp.json().get("calendars", {}).get("primary", {}).get("busy", [])
        busy_intervals = [
            (
                parse_iso_datetime(b["start"]).astimezone(tz),
                parse_iso_datetime(b["end"]).astimezone(tz),
            )
            for b in busy_periods
        ]

        slots = []
        current = time_min.date()
        end_date_obj = time_max.date()
        duration = timedelta(minutes=duration_minutes)

        while current <= end_date_obj and len(slots) < 10:
            work_start = datetime(current.year, current.month, current.day, start_hour, 0, tzinfo=tz)
            work_end = datetime(current.year, current.month, current.day, end_hour, 0, tzinfo=tz)

            if work_start < datetime.now(tz) + timedelta(minutes=15):
                now_rounded = datetime.now(tz).replace(second=0, microsecond=0)
                minutes = now_rounded.minute
                next_slot = minutes + (30 - minutes % 30) if minutes % 30 != 0 else minutes
                work_start = now_rounded.replace(minute=0) + timedelta(minutes=next_slot)
                if work_start >= work_end:
                    current += timedelta(days=1)
                    continue

            free_blocks = [(work_start, work_end)]
            for busy_start, busy_end in busy_intervals:
                new_blocks = []
                for fs, fe in free_blocks:
                    if busy_end <= fs or busy_start >= fe:
                        new_blocks.append((fs, fe))
                    else:
                        if busy_start > fs:
                            new_blocks.append((fs, busy_start))
                        if busy_end < fe:
                            new_blocks.append((busy_end, fe))
                free_blocks = new_blocks

            for fs, fe in free_blocks:
                slot_start = fs
                while slot_start + duration <= fe and len(slots) < 10:
                    slots.append({
                        "start": slot_start.isoformat(),
                        "end": (slot_start + duration).isoformat(),
                    })
                    slot_start += duration

            current += timedelta(days=1)

        return {"slots": slots, "timezone": timezone_name}

    async def create_meet_event(
        self,
        profile_id: str,
        title: str,
        start: str,
        end: str,
        attendees: list[str] | None = None,
        description: str = "",
        timezone_override: str | None = None,
    ) -> dict:
        access_token = await self._get_valid_token(profile_id)

        if timezone_override:
            tz_name = timezone_override
        else:
            supabase = get_supabase_admin_client()
            profile = await supabase.table("profiles") \
                .select("timezone") \
                .eq("id", profile_id) \
                .single() \
                .execute_async()
            tz_name = (profile.data or {}).get("timezone") or "UTC"

        event_body: dict = {
            "summary": title,
            "description": description,
            "start": {"dateTime": _strip_offset(start), "timeZone": tz_name},
            "end": {"dateTime": _strip_offset(end), "timeZone": tz_name},
            "conferenceData": {
                "createRequest": {
                    "requestId": str(uuid.uuid4()),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                },
            },
        }
        if attendees:
            event_body["attendees"] = [{"email": e} for e in attendees]

        client = get_async_http_client()
        resp = await _send_with_backoff(
            lambda: client.post(
                f"{GOOGLE_CALENDAR_API}/calendars/primary/events?conferenceDataVersion=1",
                json=event_body,
                headers={"Authorization": f"Bearer {access_token}"},
            ),
            label="create_meet_event",
        )

        if resp.status_code not in (200, 201):
            logger.error(f"Google create event failed: {resp.text}")
            raise ValueError("Failed to create Google Calendar event")

        data = resp.json()
        meet_link = ""
        for ep in data.get("conferenceData", {}).get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri", "")
                break
        entry_points = data.get("conferenceData", {}).get("entryPoints", [])
        if not meet_link and entry_points:
            meet_link = entry_points[0].get("uri", "")

        if not meet_link:
            logger.error(f"Google Calendar event created but no Meet link: {data.get('id')}")
            raise ValueError("Google Calendar event created but no Meet link was generated")

        return {
            "event_id": data["id"],
            "meet_link": meet_link,
            "html_link": data.get("htmlLink", ""),
        }

    async def create_calendar_event(
        self,
        profile_id: str,
        title: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
    ) -> dict:
        access_token = await self._get_valid_token(profile_id)

        supabase = get_supabase_admin_client()
        profile = await supabase.table("profiles") \
            .select("timezone") \
            .eq("id", profile_id) \
            .single() \
            .execute_async()
        timezone = (profile.data or {}).get("timezone") or "UTC"

        event_body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": _strip_offset(start), "timeZone": timezone},
            "end": {"dateTime": _strip_offset(end), "timeZone": timezone},
        }

        if location:
            event_body["location"] = location

        client = get_async_http_client()
        resp = await _send_with_backoff(
            lambda: client.post(
                f"{GOOGLE_CALENDAR_API}/calendars/primary/events",
                json=event_body,
                headers={"Authorization": f"Bearer {access_token}"},
            ),
            label="create_calendar_event",
        )

        if resp.status_code not in (200, 201):
            logger.error(f"Google create calendar event failed: {resp.text}")
            raise ValueError("Failed to create Google Calendar event")

        data = resp.json()
        return {
            "event_id": data["id"],
            "html_link": data.get("htmlLink", ""),
        }

    async def backfill_recall_registrations(self) -> dict:
        """Register all active Google Calendar connections missing recall_calendar_id.
        Call this once at rollout or via admin endpoint."""
        from app.config import get_settings
        settings = get_settings()
        if not settings.CALENDAR_INTELLIGENCE_ENABLED:
            return {"skipped": True, "reason": "feature disabled"}

        supabase = get_supabase_admin_client()
        result = await supabase.table("user_connections") \
            .select("profile_id, organization_id") \
            .eq("provider", "google_calendar") \
            .eq("is_active", True) \
            .is_("recall_calendar_id", "null") \
            .execute_async()

        connections = result.data or []
        registered = 0
        failed = 0
        failed_profiles = []
        for conn in connections:
            try:
                success = await self.register_with_recall(conn["profile_id"], conn["organization_id"])
                if success:
                    registered += 1
                else:
                    failed += 1
                    failed_profiles.append(conn["profile_id"])
            except Exception as e:
                logger.error(f"Backfill register failed for profile={conn['profile_id']}: {e}")
                failed += 1
                failed_profiles.append(conn["profile_id"])

        logger.info(f"Calendar backfill complete: {registered} registered, {failed} failed, {len(connections)} total")
        return {"total": len(connections), "registered": registered, "failed": failed, "failed_profiles": failed_profiles}


def get_google_calendar_service() -> GoogleCalendarService:
    return GoogleCalendarService()
