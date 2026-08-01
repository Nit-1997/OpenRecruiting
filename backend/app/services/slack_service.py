"""
Slack workspace integration — OAuth, token rotation, DM / message /
modal / home-tab senders, and installation health.

DELIBERATE DUPLICATION: this file is ported byte-for-byte from
`backend/v1/app/services/slack_service.py`. v2 cannot import from
v1 (separate FastAPI process, separate sys.path) and a partial port
would carry too much risk — the SlackService class is a tightly coupled
unit (encryption + token refresh + API calls share the same lock and
state machine).

This is the same drift risk called out in the audit (`recall_service.py`
and `feedback_job_service.py` have the same problem). The right
long-term fix is a shared package; the short-term fix is "keep them in
lockstep when either changes". A future commit should extract these
into `backend/shared/services/` and import from both backends.

The only methods the v2 recall webhook handler actually uses today are
`get_bot_token_for_team` and `send_dm` (via `notifications.py`); the
rest is here so the rest of v2 can reach the same surface area as v1
when other features port over.
"""

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
import asyncio

from cryptography.fernet import Fernet, InvalidToken
from app.config import get_settings
from app.services.supabase import get_supabase_admin_client, get_async_http_client
from app.logging_config import get_logger
from app.utils import parse_iso_datetime

logger = get_logger(__name__)

SLACK_API_BASE = "https://slack.com/api"
AUTH_ERROR_CODES = {"invalid_auth", "token_revoked", "account_inactive", "not_authed"}


class SlackServiceError(ValueError):
    pass


class SlackReauthRequiredError(SlackServiceError, ValueError):
    pass


class SlackService:
    def __init__(self):
        settings = get_settings()
        key = settings.SLACK_ENCRYPTION_KEY
        self._fernet = Fernet(key.encode()) if key else None
        self._refresh_lock_stale_seconds = 120
        self._refresh_buffer_seconds = 120
        self._refresh_wait_attempts = 8
        self._refresh_wait_interval_seconds = 0.25
        self._lock_owner = f"slack-svc-{uuid.uuid4()}"

    def encrypt_token(self, token: str) -> str:
        if not self._fernet:
            raise RuntimeError("SLACK_ENCRYPTION_KEY not configured")
        return self._fernet.encrypt(token.encode()).decode()

    def decrypt_token(self, encrypted: str) -> str:
        if not self._fernet:
            raise RuntimeError("SLACK_ENCRYPTION_KEY not configured")
        return self._fernet.decrypt(encrypted.encode()).decode()

    def create_oauth_state(self, user_id: str, org_id: str) -> str:
        if not self._fernet:
            raise RuntimeError("SLACK_ENCRYPTION_KEY not configured")
        payload = json.dumps({
            "user_id": user_id,
            "org_id": org_id,
            "exp": int(time.time()) + 600,
        })
        return self._fernet.encrypt(payload.encode()).decode()

    def verify_oauth_state(self, state: str) -> dict:
        if not self._fernet:
            raise RuntimeError("SLACK_ENCRYPTION_KEY not configured")
        try:
            decrypted = self._fernet.decrypt(state.encode()).decode()
            data = json.loads(decrypted)
            if data.get("exp", 0) < time.time():
                raise ValueError("OAuth state expired")
            return data
        except InvalidToken:
            raise ValueError("Invalid OAuth state")

    async def exchange_code(self, code: str) -> dict:
        settings = get_settings()
        client = get_async_http_client()
        resp = await client.post(
            f"{SLACK_API_BASE}/oauth.v2.access",
            data={
                "client_id": settings.SLACK_CLIENT_ID,
                "client_secret": settings.SLACK_CLIENT_SECRET,
                "code": code,
                "redirect_uri": settings.SLACK_REDIRECT_URI,
            },
        )
        data = resp.json()
        if not data.get("ok"):
            logger.error(f"Slack OAuth exchange failed: {data.get('error')}")
            raise ValueError(f"Slack OAuth failed: {data.get('error')}")
        return data

    async def _exchange_refresh_token(self, refresh_token: str) -> dict:
        settings = get_settings()
        client = get_async_http_client()
        resp = await client.post(
            f"{SLACK_API_BASE}/oauth.v2.access",
            data={
                "client_id": settings.SLACK_CLIENT_ID,
                "client_secret": settings.SLACK_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        data = resp.json() if resp.content else {}
        if not data.get("ok"):
            error = str(data.get("error") or "unknown_error")
            logger.warning(f"Slack token refresh failed: error={error}")
            raise SlackReauthRequiredError(f"Slack token refresh failed: {error}")
        return data

    def _parse_expiry(self, installation: dict) -> datetime | None:
        raw = installation.get("token_expires_at")
        if not raw:
            return None
        try:
            return parse_iso_datetime(str(raw)).astimezone(timezone.utc)
        except ValueError:
            return None

    def _should_refresh(self, installation: dict, *, force_refresh: bool = False) -> bool:
        if force_refresh:
            return True
        exp = self._parse_expiry(installation)
        if not exp:
            return False
        return exp <= datetime.now(timezone.utc) + timedelta(seconds=self._refresh_buffer_seconds)

    async def _acquire_refresh_lock(self, installation: dict) -> bool:
        install_id = installation.get("id")
        if not install_id:
            return False
        now = datetime.now(timezone.utc)
        current_lock_raw = installation.get("refresh_lock_at")

        expected_lock: str | None = None
        if current_lock_raw:
            try:
                lock_dt = parse_iso_datetime(str(current_lock_raw)).astimezone(timezone.utc)
                age = (now - lock_dt).total_seconds()
                if age <= self._refresh_lock_stale_seconds:
                    owner = installation.get("refresh_lock_owner")
                    return owner == self._lock_owner
                expected_lock = str(current_lock_raw)
            except ValueError:
                expected_lock = str(current_lock_raw)

        supabase = get_supabase_admin_client()
        update = (
            supabase.table("slack_installations")
            .update(
                {
                    "refresh_lock_at": now.isoformat(),
                    "refresh_lock_owner": self._lock_owner,
                    "updated_at": now.isoformat(),
                }
            )
            .eq("id", install_id)
        )
        if expected_lock is None:
            update = update.is_("refresh_lock_at", "null")
        else:
            update = update.eq("refresh_lock_at", expected_lock)

        result = await update.execute_async()
        return bool(result.data)

    async def _release_refresh_lock(self, installation_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        supabase = get_supabase_admin_client()
        await (
            supabase.table("slack_installations")
            .update(
                {
                    "refresh_lock_at": None,
                    "refresh_lock_owner": None,
                    "updated_at": now,
                }
            )
            .eq("id", installation_id)
            .eq("refresh_lock_owner", self._lock_owner)
            .execute_async()
        )

    async def _mark_needs_reauth(self, installation_id: str, *, error_code: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        supabase = get_supabase_admin_client()
        await (
            supabase.table("slack_installations")
            .update(
                {
                    "auth_state": "needs_reauth",
                    "last_auth_error_code": error_code,
                    "last_auth_error_at": now,
                    "reauth_notified_at": now,
                    "refresh_lock_at": None,
                    "refresh_lock_owner": None,
                    "updated_at": now,
                }
            )
            .eq("id", installation_id)
            .execute_async()
        )

    async def _refresh_bot_token(
        self,
        installation: dict,
        *,
        team_id: str,
        reason: str,
        force_refresh: bool = False,
    ) -> dict:
        install_id = installation.get("id")
        if not install_id:
            raise SlackServiceError(f"Slack installation missing id for team={team_id}")

        refresh_token_encrypted = installation.get("refresh_token_encrypted")
        if not refresh_token_encrypted:
            await self._mark_needs_reauth(install_id, error_code="missing_refresh_token")
            raise SlackReauthRequiredError(
                f"Slack team {team_id} requires reconnect (missing refresh token)"
            )

        if not await self._acquire_refresh_lock(installation):
            for _ in range(self._refresh_wait_attempts):
                await asyncio.sleep(self._refresh_wait_interval_seconds)
                latest = await self.get_installation_by_team(team_id)
                if not latest:
                    raise ValueError(f"No active installation for team {team_id}")
                if str(latest.get("auth_state") or "healthy") == "needs_reauth":
                    raise SlackReauthRequiredError(f"Slack team {team_id} requires reconnect")
                if not self._should_refresh(latest, force_refresh=force_refresh):
                    return latest
            raise SlackServiceError(
                f"Slack refresh lock contention for team={team_id}: token still stale after wait"
            )

        supabase = get_supabase_admin_client()
        now = datetime.now(timezone.utc).isoformat()
        await (
            supabase.table("slack_installations")
            .update(
                {
                    "auth_state": "refreshing",
                    "last_refresh_attempt_at": now,
                    "updated_at": now,
                }
            )
            .eq("id", install_id)
            .eq("refresh_lock_owner", self._lock_owner)
            .execute_async()
        )

        try:
            refresh_token = self.decrypt_token(refresh_token_encrypted)
            token_data = await self._exchange_refresh_token(refresh_token)
            new_access = token_data.get("access_token")
            if not new_access:
                await self._mark_needs_reauth(install_id, error_code="missing_access_token")
                raise SlackReauthRequiredError(
                    f"Slack team {team_id} refresh response missing access token"
                )

            expires_in = int(token_data.get("expires_in") or 0)
            issued_at = datetime.now(timezone.utc)
            expires_at = issued_at + timedelta(seconds=expires_in) if expires_in > 0 else None
            new_refresh_token = token_data.get("refresh_token") or refresh_token

            update: dict[str, Any] = {
                "bot_token_encrypted": self.encrypt_token(new_access),
                "refresh_token_encrypted": self.encrypt_token(new_refresh_token),
                "token_issued_at": issued_at.isoformat(),
                "token_expires_at": expires_at.isoformat() if expires_at else None,
                "token_type": token_data.get("token_type"),
                "auth_state": "healthy",
                "last_auth_error_code": None,
                "last_auth_error_at": None,
                "last_refresh_success_at": issued_at.isoformat(),
                "updated_at": issued_at.isoformat(),
            }
            await (
                supabase.table("slack_installations")
                .update(update)
                .eq("id", install_id)
                .eq("refresh_lock_owner", self._lock_owner)
                .execute_async()
            )
            logger.info(
                "slack_token_refresh_success",
                extra={
                    "event": "slack_token_refresh_success",
                    "team_id": team_id,
                    "reason": reason,
                    "expires_at": update["token_expires_at"],
                },
            )
        except SlackReauthRequiredError:
            raise
        except Exception as e:
            logger.error(
                "slack_token_refresh_failed",
                extra={
                    "event": "slack_token_refresh_failed",
                    "team_id": team_id,
                    "reason": reason,
                    "error": str(e),
                },
            )
            raise SlackServiceError(f"Slack token refresh failed for team={team_id}: {e}") from e
        finally:
            await self._release_refresh_lock(install_id)

        latest = await self.get_installation_by_team(team_id)
        if not latest:
            raise ValueError(f"No active installation for team {team_id}")
        return latest

    async def _mark_needs_reauth_by_team(self, team_id: str, error_code: str) -> None:
        installation = await self.get_installation_by_team(team_id)
        if not installation:
            return
        install_id = installation.get("id")
        if not install_id:
            return
        await self._mark_needs_reauth(install_id, error_code=error_code)

    @staticmethod
    def _is_auth_error(data: dict) -> bool:
        return str(data.get("error") or "") in AUTH_ERROR_CODES

    async def _slack_api_call(
        self,
        *,
        method: str,
        endpoint: str,
        bot_token: str,
        team_id: str | None = None,
        json_payload: dict | None = None,
        params: dict | None = None,
        retry_on_auth: bool = True,
    ) -> dict:
        client = get_async_http_client()
        resp = await client.request(
            method=method,
            url=f"{SLACK_API_BASE}/{endpoint}",
            json=json_payload,
            params=params,
            headers={"Authorization": f"Bearer {bot_token}"},
        )
        data = resp.json() if resp.content else {}
        if data.get("ok"):
            return data

        if not (retry_on_auth and team_id and self._is_auth_error(data)):
            return data

        try:
            refreshed_token = await self.get_bot_token_for_team(
                team_id,
                force_refresh=True,
                refresh_reason=f"api_auth_error:{endpoint}",
            )
        except SlackReauthRequiredError:
            await self._mark_needs_reauth_by_team(team_id, error_code=str(data.get("error") or "invalid_auth"))
            raise

        retry_resp = await client.request(
            method=method,
            url=f"{SLACK_API_BASE}/{endpoint}",
            json=json_payload,
            params=params,
            headers={"Authorization": f"Bearer {refreshed_token}"},
        )
        retry_data = retry_resp.json() if retry_resp.content else {}
        if retry_data.get("ok"):
            return retry_data

        if self._is_auth_error(retry_data):
            await self._mark_needs_reauth_by_team(
                team_id,
                error_code=str(retry_data.get("error") or "invalid_auth"),
            )
            raise SlackReauthRequiredError(f"Slack auth failed after refresh for team={team_id}")

        return retry_data

    async def send_message(
        self,
        bot_token: str,
        channel: str,
        text: str,
        blocks: list | None = None,
        thread_ts: str | None = None,
        team_id: str | None = None,
    ) -> dict:
        payload = {"channel": channel, "text": text}
        if blocks:
            payload["blocks"] = blocks
        if thread_ts:
            payload["thread_ts"] = thread_ts
        data = await self._slack_api_call(
            method="POST",
            endpoint="chat.postMessage",
            bot_token=bot_token,
            team_id=team_id,
            json_payload=payload,
        )
        if not data.get("ok"):
            logger.error(f"Slack send_message failed: {data.get('error')}")
        return data

    async def update_message(
        self,
        bot_token: str,
        channel: str,
        ts: str,
        text: str,
        blocks: list | None = None,
        team_id: str | None = None,
    ) -> dict:
        payload = {"channel": channel, "ts": ts, "text": text}
        if blocks:
            payload["blocks"] = blocks
        data = await self._slack_api_call(
            method="POST",
            endpoint="chat.update",
            bot_token=bot_token,
            team_id=team_id,
            json_payload=payload,
        )
        if not data.get("ok"):
            logger.error(f"Slack update_message failed: {data.get('error')}")
        return data

    async def open_dm_channel(self, bot_token: str, slack_user_id: str, team_id: str | None = None) -> str:
        data = await self._slack_api_call(
            method="POST",
            endpoint="conversations.open",
            bot_token=bot_token,
            team_id=team_id,
            json_payload={"users": slack_user_id},
        )
        if not data.get("ok"):
            logger.error(f"Slack open_dm_channel failed: {data.get('error')}")
            raise ValueError(f"Failed to open DM: {data.get('error')}")
        return data["channel"]["id"]

    async def send_dm(
        self,
        bot_token: str,
        slack_user_id: str,
        text: str,
        blocks: list | None = None,
        team_id: str | None = None,
    ) -> dict:
        channel = await self.open_dm_channel(bot_token, slack_user_id, team_id=team_id)
        return await self.send_message(
            bot_token,
            channel,
            text,
            blocks,
            team_id=team_id,
        )

    async def publish_home_tab(
        self,
        bot_token: str,
        slack_user_id: str,
        blocks: list,
        team_id: str | None = None,
    ) -> dict:
        data = await self._slack_api_call(
            method="POST",
            endpoint="views.publish",
            bot_token=bot_token,
            team_id=team_id,
            json_payload={
                "user_id": slack_user_id,
                "view": {
                    "type": "home",
                    "blocks": blocks,
                },
            },
        )
        if not data.get("ok"):
            logger.error(f"Slack publish_home_tab failed: {data.get('error')}")
        return data

    async def get_user_info(
        self,
        bot_token: str,
        slack_user_id: str,
        team_id: str | None = None,
    ) -> dict:
        data = await self._slack_api_call(
            method="GET",
            endpoint="users.info",
            bot_token=bot_token,
            team_id=team_id,
            params={"user": slack_user_id},
        )
        if not data.get("ok"):
            logger.error(f"Slack get_user_info failed: {data.get('error')}")
        return data

    async def get_installation_by_team(self, team_id: str) -> dict | None:
        supabase = get_supabase_admin_client()
        result = await supabase.table("slack_installations") \
            .select("*") \
            .eq("slack_team_id", team_id) \
            .eq("is_active", True) \
            .limit(1) \
            .execute_async()
        return result.data[0] if result.data else None

    async def get_connection(self, slack_user_id: str, slack_team_id: str) -> dict | None:
        supabase = get_supabase_admin_client()
        result = await supabase.table("slack_connections") \
            .select("*") \
            .eq("slack_user_id", slack_user_id) \
            .eq("slack_team_id", slack_team_id) \
            .eq("is_active", True) \
            .limit(1) \
            .execute_async()
        return result.data[0] if result.data else None

    async def get_bot_token_for_team(
        self,
        team_id: str,
        *,
        force_refresh: bool = False,
        refresh_reason: str = "lazy",
    ) -> str:
        installation = await self.get_installation_by_team(team_id)
        if not installation:
            raise ValueError(f"No active installation for team {team_id}")
        if str(installation.get("auth_state") or "healthy") == "needs_reauth":
            raise SlackReauthRequiredError(f"Slack team {team_id} requires reconnect")
        if not installation.get("bot_token_encrypted"):
            await self._mark_needs_reauth_by_team(team_id, "missing_access_token")
            raise SlackReauthRequiredError(f"Slack team {team_id} requires reconnect")

        if self._should_refresh(installation, force_refresh=force_refresh):
            installation = await self._refresh_bot_token(
                installation,
                team_id=team_id,
                reason=refresh_reason,
                force_refresh=force_refresh,
            )

        return self.decrypt_token(installation["bot_token_encrypted"])

    async def open_modal(
        self,
        bot_token: str,
        trigger_id: str,
        view: dict,
        team_id: str | None = None,
    ) -> dict:
        data = await self._slack_api_call(
            method="POST",
            endpoint="views.open",
            bot_token=bot_token,
            team_id=team_id,
            json_payload={"trigger_id": trigger_id, "view": view},
        )
        if not data.get("ok"):
            logger.error(f"Slack open_modal failed: {data.get('error')}")
        return data

    async def refresh_expiring_installations(
        self,
        *,
        lookahead_seconds: int | None = None,
        batch_size: int | None = None,
    ) -> dict[str, int]:
        settings = get_settings()
        lookahead = lookahead_seconds or settings.SLACK_TOKEN_REFRESH_LOOKAHEAD_SECONDS
        limit = batch_size or settings.SLACK_TOKEN_REFRESH_BATCH_SIZE
        threshold = (datetime.now(timezone.utc) + timedelta(seconds=lookahead)).isoformat()

        supabase = get_supabase_admin_client()
        result = await (
            supabase.table("slack_installations")
            .select("id, slack_team_id, token_expires_at, auth_state, refresh_token_encrypted")
            .eq("is_active", True)
            .eq("auth_state", "healthy")
            .not_null("token_expires_at")
            .lte("token_expires_at", threshold)
            .order("token_expires_at", desc=False)
            .limit(limit)
            .execute_async()
        )

        rows = result.data or []
        refreshed = 0
        reauth = 0
        failed = 0
        for row in rows:
            team_id = row.get("slack_team_id")
            if not team_id:
                continue
            try:
                await self.get_bot_token_for_team(
                    team_id,
                    force_refresh=True,
                    refresh_reason="proactive",
                )
                refreshed += 1
            except SlackReauthRequiredError:
                reauth += 1
            except Exception:
                failed += 1
        return {
            "checked": len(rows),
            "refreshed": refreshed,
            "reauth_required": reauth,
            "failed": failed,
        }

    async def get_installation_health_summary(self) -> dict[str, Any]:
        supabase = get_supabase_admin_client()
        result = await (
            supabase.table("slack_installations")
            .select("slack_team_id, auth_state, token_expires_at, is_active")
            .eq("is_active", True)
            .execute_async()
        )
        rows = result.data or []
        now = datetime.now(timezone.utc)
        summary = {
            "total_active_installations": len(rows),
            "auth_state_counts": {
                "healthy": 0,
                "refreshing": 0,
                "needs_reauth": 0,
                "disabled": 0,
                "unknown": 0,
            },
            "expiry_buckets": {
                "lt_15m": 0,
                "lt_1h": 0,
                "gte_1h": 0,
                "missing": 0,
            },
        }
        for row in rows:
            state = str(row.get("auth_state") or "unknown")
            if state not in summary["auth_state_counts"]:
                state = "unknown"
            summary["auth_state_counts"][state] += 1

            exp = self._parse_expiry(row)
            if not exp:
                summary["expiry_buckets"]["missing"] += 1
                continue
            delta = (exp - now).total_seconds()
            if delta < 900:
                summary["expiry_buckets"]["lt_15m"] += 1
            elif delta < 3600:
                summary["expiry_buckets"]["lt_1h"] += 1
            else:
                summary["expiry_buckets"]["gte_1h"] += 1
        return summary

    async def force_refresh_team_token(self, team_id: str) -> dict[str, Any]:
        await self.get_bot_token_for_team(
            team_id,
            force_refresh=True,
            refresh_reason="manual_force_refresh",
        )
        installation = await self.get_installation_by_team(team_id)
        return {
            "team_id": team_id,
            "auth_state": installation.get("auth_state") if installation else None,
            "token_expires_at": installation.get("token_expires_at") if installation else None,
            "refreshed": bool(installation),
        }

    async def backfill_auth_state(self) -> dict[str, int]:
        supabase = get_supabase_admin_client()
        result = await (
            supabase.table("slack_installations")
            .select("id, auth_state, refresh_token_encrypted, token_expires_at")
            .eq("is_active", True)
            .execute_async()
        )

        rows = result.data or []
        updated = 0
        skipped = 0
        for row in rows:
            has_rotation = bool(row.get("refresh_token_encrypted")) and bool(row.get("token_expires_at"))
            auth_state = str(row.get("auth_state") or "")
            if has_rotation:
                skipped += 1
                continue
            if auth_state == "needs_reauth":
                skipped += 1
                continue
            install_id = row.get("id")
            if not install_id:
                skipped += 1
                continue
            await self._mark_needs_reauth(install_id, error_code="missing_rotation_fields")
            updated += 1

        return {
            "checked": len(rows),
            "updated_to_needs_reauth": updated,
            "skipped": skipped,
        }

    async def find_slack_user_by_profile_email(
        self, email: str, organization_id: str | None = None, slack_team_id: str | None = None
    ) -> str | None:
        if not email:
            return None
        supabase = get_supabase_admin_client()
        query = supabase.table("profiles") \
            .select("id") \
            .eq("email", email.lower())
        if organization_id:
            query = query.eq("organization_id", organization_id)
        result = await query.execute_async()
        if not result.data:
            return None
        profile_id = result.data[0]["id"]
        conn_query = supabase.table("slack_connections") \
            .select("slack_user_id") \
            .eq("profile_id", profile_id) \
            .eq("is_active", True)
        if slack_team_id:
            conn_query = conn_query.eq("slack_team_id", slack_team_id)
        conn = await conn_query.limit(1).execute_async()
        return conn.data[0]["slack_user_id"] if conn.data else None


def get_slack_service() -> SlackService:
    return SlackService()
