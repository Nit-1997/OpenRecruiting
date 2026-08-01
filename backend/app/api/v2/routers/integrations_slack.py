"""
Slack integration routes for v2.

Mounted under /api/v2/integrations/slack:
  GET    /install     Initiate OAuth — returns redirect_url for the browser
  GET    /callback    OAuth callback — no auth, called by Slack
  GET    /status      Current connection status for the caller's org
  DELETE /disconnect  Deactivate Slack connection
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
)
from app.api.v2.core.exceptions import ForbiddenError, NotFoundError
from app.config import get_settings
from app.logging_config import get_logger
from app.services.slack_blocks import welcome_blocks
from app.services.slack_service import get_slack_service
from app.services.supabase import get_supabase_admin_client

logger = get_logger(__name__)

router = APIRouter(prefix="/integrations/slack", tags=["v2/integrations/slack"])

SLACK_OAUTH_SCOPES = "chat:write,im:history,im:read,im:write,app_mentions:read,users:read,channels:read"


class SlackInstallResponse(BaseModel):
    redirect_url: str


class SlackStatusResponse(BaseModel):
    connected: bool
    team_name: Optional[str] = None
    connected_at: Optional[str] = None
    healthy: Optional[bool] = None
    needs_reauth: Optional[bool] = None
    auth_state: Optional[str] = None
    token_expires_at: Optional[str] = None
    last_auth_error_code: Optional[str] = None


@router.get("/install", response_model=SlackInstallResponse)
async def install(
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
) -> SlackInstallResponse:
    supabase = get_supabase_admin_client()
    sub = await supabase.table("subscriptions") \
        .select("plan_id, plans(slack_enabled)") \
        .eq("organization_id", current.organization_id_str) \
        .eq("status", "active") \
        .limit(1) \
        .execute_async()

    sub_data = sub.data[0] if sub.data else None
    if not sub_data or not sub_data.get("plans", {}).get("slack_enabled"):
        raise ForbiddenError("Slack integration not available on your current plan")

    settings = get_settings()
    service = get_slack_service()
    state = service.create_oauth_state(str(current.user.id), current.organization_id_str)

    params = urlencode({
        "client_id": settings.SLACK_CLIENT_ID,
        "scope": SLACK_OAUTH_SCOPES,
        "redirect_uri": settings.SLACK_REDIRECT_URI,
        "state": state,
    })
    return SlackInstallResponse(redirect_url=f"https://slack.com/oauth/v2/authorize?{params}")


@router.get("/callback")
async def callback(request: Request) -> RedirectResponse:
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    settings = get_settings()
    frontend_url = f"{settings.APP_URL}/view/integrations"

    if error:
        logger.warning(f"Slack OAuth denied: {error}")
        return RedirectResponse(f"{frontend_url}?slack=error&reason={quote(str(error))}")

    if not code or not state:
        return RedirectResponse(f"{frontend_url}?slack=error&reason=missing_params")

    service = get_slack_service()
    try:
        state_data = service.verify_oauth_state(state)
    except ValueError as e:
        logger.warning(f"Slack OAuth state verification failed: {e}")
        return RedirectResponse(f"{frontend_url}?slack=error&reason=invalid_state")

    user_id = state_data["user_id"]
    org_id = state_data["org_id"]

    try:
        oauth_data = await service.exchange_code(code)
    except ValueError as e:
        logger.error(f"Slack OAuth code exchange failed: {e}")
        return RedirectResponse(f"{frontend_url}?slack=error&reason=exchange_failed")

    team = oauth_data.get("team", {})
    team_id = team.get("id")
    team_name = team.get("name")
    bot_token = oauth_data.get("access_token")
    refresh_token = oauth_data.get("refresh_token")
    expires_in = oauth_data.get("expires_in")
    token_type = oauth_data.get("token_type")
    bot_user_id = oauth_data.get("bot_user_id")
    authed_user = oauth_data.get("authed_user", {})
    slack_user_id = authed_user.get("id")
    scopes = oauth_data.get("scope", "")

    if not team_id or not bot_token or not slack_user_id:
        logger.error(
            f"Slack OAuth callback missing required fields: "
            f"team_id={team_id}, has_bot_token={bool(bot_token)}, slack_user_id={slack_user_id}"
        )
        return RedirectResponse(f"{frontend_url}?slack=error&reason=incomplete_oauth_payload")

    logger.info(
        f"Slack OAuth callback: profile={user_id}, team={team_id}, "
        f"authed_slack_user={slack_user_id}, bot_user={bot_user_id}"
    )

    encrypted_token = service.encrypt_token(bot_token)
    encrypted_refresh = service.encrypt_token(refresh_token) if refresh_token else None
    now = datetime.now(timezone.utc)
    token_expires_at = None
    if expires_in:
        try:
            token_expires_at = (now + timedelta(seconds=int(expires_in))).isoformat()
        except (TypeError, ValueError):
            token_expires_at = None
    auth_state = "healthy" if encrypted_refresh and token_expires_at else "needs_reauth"
    auth_error_code = None if auth_state == "healthy" else "missing_rotation_fields"

    supabase = get_supabase_admin_client()

    existing_install = await supabase.table("slack_installations") \
        .select("id") \
        .eq("slack_team_id", team_id) \
        .limit(1) \
        .execute_async()

    install_data = {
        "slack_team_id": team_id,
        "slack_team_name": team_name,
        "slack_team_domain": oauth_data.get("team", {}).get("domain"),
        "bot_token_encrypted": encrypted_token,
        "bot_user_id": bot_user_id,
        "installed_by": user_id,
        "scopes": scopes,
        "is_active": True,
        "refresh_token_encrypted": encrypted_refresh,
        "token_expires_at": token_expires_at,
        "token_issued_at": now.isoformat(),
        "token_type": token_type,
        "auth_state": auth_state,
        "last_auth_error_code": auth_error_code,
        "last_auth_error_at": now.isoformat() if auth_error_code else None,
        "last_refresh_attempt_at": None,
        "last_refresh_success_at": None,
        "refresh_lock_at": None,
        "refresh_lock_owner": None,
        "updated_at": now.isoformat(),
    }

    if existing_install.data:
        await supabase.table("slack_installations") \
            .update(install_data) \
            .eq("slack_team_id", team_id) \
            .execute_async()
    else:
        await supabase.table("slack_installations") \
            .insert(install_data) \
            .execute_async()

    await supabase.table("slack_connections") \
        .update({"is_active": False}) \
        .eq("organization_id", org_id) \
        .eq("is_active", True) \
        .execute_async()

    existing_conn = await supabase.table("slack_connections") \
        .select("id") \
        .eq("slack_user_id", slack_user_id) \
        .eq("slack_team_id", team_id) \
        .limit(1) \
        .execute_async()

    conn_data = {
        "slack_user_id": slack_user_id,
        "slack_team_id": team_id,
        "profile_id": user_id,
        "organization_id": org_id,
        "is_active": True,
    }

    if existing_conn.data:
        await supabase.table("slack_connections") \
            .update(conn_data) \
            .eq("slack_user_id", slack_user_id) \
            .eq("slack_team_id", team_id) \
            .execute_async()
    else:
        await supabase.table("slack_connections") \
            .insert(conn_data) \
            .execute_async()

    try:
        await service.send_dm(
            bot_token,
            slack_user_id,
            "Welcome to OpenRecruiting!",
            welcome_blocks(),
            team_id=team_id,
        )
    except Exception as e:
        logger.warning(f"Failed to send welcome DM: {e}")

    return RedirectResponse(f"{frontend_url}?slack=connected")


@router.get("/status", response_model=SlackStatusResponse)
async def status(
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
) -> SlackStatusResponse:
    supabase = get_supabase_admin_client()
    result = await supabase.table("slack_connections") \
        .select("*, slack_installations(slack_team_name, auth_state, token_expires_at, last_auth_error_code)") \
        .eq("organization_id", current.organization_id_str) \
        .eq("is_active", True) \
        .limit(1) \
        .execute_async()

    row = result.data[0] if result.data else None
    if not row:
        return SlackStatusResponse(connected=False, healthy=False, needs_reauth=False)

    install = row.get("slack_installations", {}) or {}
    if isinstance(install, list):
        install = install[0] if install else {}

    auth_state = install.get("auth_state")
    needs_reauth = auth_state == "needs_reauth"
    return SlackStatusResponse(
        connected=True,
        team_name=install.get("slack_team_name"),
        connected_at=row.get("created_at"),
        healthy=not needs_reauth,
        needs_reauth=needs_reauth,
        auth_state=auth_state,
        token_expires_at=install.get("token_expires_at"),
        last_auth_error_code=install.get("last_auth_error_code"),
    )


@router.delete("/disconnect")
async def disconnect(
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
) -> dict:
    supabase = get_supabase_admin_client()
    result = await supabase.table("slack_connections") \
        .update({"is_active": False}) \
        .eq("organization_id", current.organization_id_str) \
        .eq("is_active", True) \
        .execute_async()

    if not result.data:
        raise NotFoundError("No active Slack connection")

    return {"status": "ok", "message": "Slack disconnected"}
