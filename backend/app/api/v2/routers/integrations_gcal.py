"""
Google Calendar integration routes for v2.

Mounted under /api/v2/integrations/google-calendar:
  GET    /install              Initiate OAuth — returns redirect_url for the browser
  GET    /callback             OAuth callback — no auth, called by Google
  GET    /status               Current connection status for the caller
  PATCH  /calendar-watch       Toggle calendar-watch on/off
  PATCH  /auto-join-untracked  Toggle auto-join for untracked meetings
  DELETE /disconnect           Remove Google Calendar connection
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.core.exceptions import NotFoundError, UpstreamServiceError
from app.config import get_settings
from app.logging_config import get_logger
from app.services.google_calendar_service import get_google_calendar_service

logger = get_logger(__name__)

router = APIRouter(prefix="/integrations/google-calendar", tags=["v2/integrations/gcal"])


class GcalInstallResponse(BaseModel):
    redirect_url: str


class GcalStatusResponse(BaseModel):
    connected: bool
    email: str | None = None
    connected_at: str | None = None
    calendar_watch_enabled: bool = True
    auto_join_untracked: bool = False


class CalendarWatchToggle(BaseModel):
    enabled: bool


class AutoJoinToggle(BaseModel):
    enabled: bool


@router.get("/install", response_model=GcalInstallResponse)
async def install(
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
) -> GcalInstallResponse:
    service = get_google_calendar_service()
    try:
        state = service.create_oauth_state(
            str(current.user.id), current.organization_id_str
        )
        redirect_url = service.build_oauth_url(state)
    except RuntimeError as e:
        raise UpstreamServiceError(str(e), status_code=503)
    return GcalInstallResponse(redirect_url=redirect_url)


@router.get("/callback")
async def callback(request: Request) -> RedirectResponse:
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    settings = get_settings()
    frontend_url = f"{settings.APP_URL}/view/integrations"

    if error:
        logger.warning(f"Google OAuth denied: {error}")
        return RedirectResponse(f"{frontend_url}?google_calendar=error&reason={quote(str(error))}")

    if not code or not state:
        return RedirectResponse(f"{frontend_url}?google_calendar=error&reason=missing_params")

    service = get_google_calendar_service()

    try:
        state_data = service.verify_oauth_state(state)
    except ValueError as e:
        logger.warning(f"Google OAuth state verification failed: {e}")
        return RedirectResponse(f"{frontend_url}?google_calendar=error&reason=invalid_state")

    user_id = state_data["user_id"]
    org_id = state_data["org_id"]

    try:
        tokens = await service.exchange_code(code)
    except ValueError as e:
        logger.error(f"Google OAuth code exchange failed: {e}")
        return RedirectResponse(f"{frontend_url}?google_calendar=error&reason=exchange_failed")

    try:
        userinfo = await service.get_userinfo(tokens["access_token"])
        email = userinfo.get("email", "")
    except Exception:
        email = ""

    if not email:
        logger.warning(f"Google Calendar OAuth: no email returned for user={user_id}")
        return RedirectResponse(f"{frontend_url}?google_calendar=error&reason=no_email")

    await service.save_connection(user_id, org_id, tokens, email)

    try:
        await service.register_with_recall(user_id, org_id)
    except Exception as e:
        logger.error(f"Google Calendar OAuth: Recall registration failed for user={user_id}: {e}")

    return RedirectResponse(f"{frontend_url}?google_calendar=connected")


@router.get("/status", response_model=GcalStatusResponse)
async def status(
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
) -> GcalStatusResponse:
    service = get_google_calendar_service()
    connection = await service.get_connection(str(current.user.id))
    if not connection:
        return GcalStatusResponse(connected=False)
    return GcalStatusResponse(
        connected=True,
        email=connection.get("provider_email"),
        connected_at=connection.get("created_at"),
        calendar_watch_enabled=connection.get("calendar_watch_enabled", True),
        auto_join_untracked=connection.get("auto_join_untracked", False),
    )


@router.patch("/calendar-watch")
async def toggle_calendar_watch(
    body: CalendarWatchToggle,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    result = await supabase.table("user_connections") \
        .update({"calendar_watch_enabled": body.enabled}) \
        .eq("profile_id", str(current.user.id)) \
        .eq("provider", "google_calendar") \
        .eq("is_active", True) \
        .execute_async()
    if not result.data:
        raise NotFoundError("No active Google Calendar connection")
    return {"calendar_watch_enabled": body.enabled}


@router.patch("/auto-join-untracked")
async def toggle_auto_join_untracked(
    body: AutoJoinToggle,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    try:
        result = await supabase.table("user_connections") \
            .update({"auto_join_untracked": body.enabled}) \
            .eq("profile_id", str(current.user.id)) \
            .eq("provider", "google_calendar") \
            .eq("is_active", True) \
            .execute_async()
    except Exception as exc:
        msg = str(exc).lower()
        if "auto_join_untracked" in msg and ("column" in msg or "schema cache" in msg):
            raise UpstreamServiceError(
                "Auto-join preference is temporarily unavailable while a database migration is pending.",
                status_code=503,
            )
        logger.error(f"Auto-join toggle failed for user={current.user.id}: {exc}")
        raise UpstreamServiceError("Failed to update auto-join preference", status_code=503)
    if not result.data:
        raise NotFoundError("No active Google Calendar connection")
    return {"auto_join_untracked": body.enabled}


@router.delete("/disconnect")
async def disconnect(
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
) -> dict:
    service = get_google_calendar_service()
    try:
        return await service.disconnect(str(current.user.id))
    except NotImplementedError as e:
        raise UpstreamServiceError(str(e), status_code=503)
    except Exception as e:
        logger.error(f"Google Calendar disconnect failed for user={current.user.id}: {e}")
        raise UpstreamServiceError("Google Calendar disconnect failed", status_code=503)
