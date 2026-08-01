"""
Auth routes for v2.

Mounted under `/api/v2/auth`:
  POST   /verify-otp   Verify invite OTP and return session tokens (public)
  GET    /me           Profile for the authenticated user

The frontend authenticates directly via `@supabase/supabase-js`; the v2 backend
is a pure JWT-verifier. This module exists only to join profile data onto the
verified user identity.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.core.exceptions import ValidationError
from app.api.v2.schemas.auth import MeResponse, VerifyOtpRequest, VerifyOtpResponse
from app.api.v2.services import auth_service
from app.config import get_settings
from app.dependencies import get_authenticated_user_id
from app.logging_config import get_logger
from app.services.signup_service import complete_user_signup, SignupBlockedError
from app.services.supabase import get_async_http_client, get_supabase_admin_client


logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["v2/auth"])


@router.post("/verify-otp", response_model=VerifyOtpResponse)
async def verify_otp(body: VerifyOtpRequest) -> VerifyOtpResponse:
    settings = get_settings()
    client = get_async_http_client()
    response = await client.post(
        f"{settings.SUPABASE_URL}/auth/v1/verify",
        json={"type": "invite", "email": body.email, "token": body.token},
        headers={"apikey": settings.SUPABASE_SECRET_KEY, "Content-Type": "application/json"},
    )
    if response.status_code != 200:
        error = response.json() if response.content else {}
        msg = (
            error.get("error_description")
            or error.get("msg")
            or error.get("message")
            or "Invalid or expired verification code"
        )
        raise ValidationError(msg)
    data = response.json()
    return VerifyOtpResponse(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
    )


@router.get("/me", response_model=MeResponse)
async def me(
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    # Decision: require_org for /me. Recruiter-product convention — a user
    # without an org has no useful surface in v2, so 403 the request and let
    # the FE surface "contact admin". Sourced from spec §"What to build"
    # routing decision.
    return await auth_service.get_me(supabase, current.user)


@router.post("/complete-signup")
async def complete_signup(user_id: str = Depends(get_authenticated_user_id)):
    try:
        return await complete_user_signup(user_id)
    except SignupBlockedError as e:
        # Deliberate raw HTTPException (not v2 ForbiddenError): FE needs a structured {"message","code"} 403 body the v2 handler can't express.
        try:
            await get_supabase_admin_client().delete_user(user_id)
        except Exception as cleanup_err:  # best-effort orphan cleanup
            logger.warning(
                "signup_blocked_cleanup_failed",
                extra={"user_id": user_id, "error": str(cleanup_err)},
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": str(e), "code": "signup_blocked"},
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        # Log the full error server-side; return a STATIC message so internal
        # detail (DB DSNs, stack internals) never leaks to the client.
        logger.error(
            "complete_signup_failed",
            extra={"user_id": user_id, "error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Signup failed. Please try again.",
        )


@router.post("/complete-onboarding")
async def complete_onboarding(user_id: str = Depends(get_authenticated_user_id)):
    """Mark the authenticated user's profile as onboarded.

    Called by landing's set-password page once the user finishes the
    welcome/password step. Ported from v1 (/user/profile/complete-onboarding);
    the update fails loud on a DB error (mapped by the global handler), and a
    no-row match means the profile does not exist yet.
    """
    result = await get_supabase_admin_client().table("profiles") \
        .update({"onboarding_completed": True}) \
        .eq("id", user_id) \
        .execute_async()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )
    return {"onboarding_completed": True}
