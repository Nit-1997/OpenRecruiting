"""No-login candidate screening portal.

Mirrors `public_feedback.py`: a candidate receives an emailed link
`{APP_URL}/screening/{token}/verify`, verifies a 6-digit OTP to mint a
session JWT, then starts the voice screening call. All endpoints are keyed by the
opaque `screening_invites.token`.

Differences from the feedback portal:
  * The invite's `expires_at` link-window is a REAL 410 gate (feedback's is mostly
    optional). `get_screening_token_record` enforces it.
  * The session JWT carries `type="screening_session"` — distinct from the feedback
    `"feedback_session"` — so the two portals' tokens are not interchangeable. We
    mint/verify it locally (not via OTPService, which is feedback-typed) to keep the
    shared service untouched.

Async invariant: all DB IO goes through the custom async Supabase client
(execute_async); never the sync `.execute` twin. The voice-token write is a
compare-and-set scoped by status so concurrent/stale starts can't clobber.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, Optional, Tuple

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.api.v2.schemas.screening import (
    ScreeningContextResponse,
    ScreeningSendOTPResponse,
    ScreeningSessionResponse,
    ScreeningStartVoiceRequest,
    ScreeningStartVoiceResponse,
    ScreeningVerifyOTPRequest,
    ScreeningVerifyOTPResponse,
)
from app.config import get_settings
from app.logging_config import get_logger
from app.services.email.service import get_email_service
from app.services.otp_service import get_otp_service
from app.services.screening_invite_service import (
    InviteExpiredError,
    get_screening_otp_service,
)
from app.services.supabase import get_supabase_admin_client
from app.utils import parse_iso_datetime

logger = get_logger(__name__)

router = APIRouter(prefix="/public/screening")

SCREENING_SESSION_TYPE = "screening_session"
SESSION_HOURS = 24

# Verified session context shared by every session-gated endpoint:
# the resolved screening invite record plus the decoded session-JWT payload.
ScreeningSession = Tuple[dict, dict]


def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return "***@***"
    local, domain = email.rsplit("@", 1)
    masked_local = "*" if len(local) <= 1 else local[0] + "***"
    return f"{masked_local}@{domain}"


def create_screening_session_token(
    token_id: str, candidate_email: str, candidate_round_id: str
) -> Tuple[str, datetime]:
    """Mint the candidate screening session JWT.

    Same claims shape as OTPService.create_session_token but with a distinct
    `type` so a feedback-session token can never satisfy the screening gate.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=SESSION_HOURS)
    payload = {
        "token_id": token_id,
        "email": candidate_email,
        "candidate_round_id": candidate_round_id,
        "type": SCREENING_SESSION_TYPE,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    settings = get_settings()
    session_token = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")
    return session_token, expires_at


def verify_screening_session_token(session_token: str) -> Optional[dict]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            session_token, settings.SUPABASE_JWT_SECRET, algorithms=["HS256"]
        )
    except jwt.ExpiredSignatureError:
        logger.warning("Screening session token expired")
        return None
    except jwt.InvalidTokenError as exc:
        logger.warning(f"Invalid screening session token: {exc}")
        return None

    if payload.get("type") != SCREENING_SESSION_TYPE:
        logger.warning("Invalid screening session token type")
        return None
    return payload


async def get_screening_token_record(token: str) -> dict:
    """Resolve a screening_invites row by token; 404 on missing, 410 on expired.

    Joins through candidate_rounds -> rounds -> requisitions so the context view
    can surface the role title + round name without a second query.
    """
    supabase = get_supabase_admin_client()
    result = await (
        supabase.table("screening_invites")
        .select(
            "*, candidate_rounds!inner(id, screening_voice_session_status, "
            "rounds!inner(id, name, requisitions!inner(role_title)))"
        )
        .eq("token", token)
        .single()
        .execute_async()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Invalid or expired screening link")

    invite = result.data

    expires_at_str = invite.get("expires_at")
    if expires_at_str:
        expires_at = (
            parse_iso_datetime(expires_at_str)
            if isinstance(expires_at_str, str)
            else expires_at_str
        )
        if datetime.now(timezone.utc) > expires_at:
            raise HTTPException(status_code=410, detail="Screening link has expired")

    return invite


def require_voice_enabled() -> None:
    """503 guard kept separate so it fires before the session gate (matches the
    feedback /start-voice ordering, where VOICE_ENABLED is checked first)."""
    settings = get_settings()
    if not settings.VOICE_ENABLED:
        raise HTTPException(status_code=503, detail="Voice screening is not enabled.")


def require_screening_session() -> Callable[..., "ScreeningSession"]:
    """FastAPI dependency enforcing the screening session-JWT gate.

    Extracts the JWT from `Authorization: Bearer` or the `session_token` query
    param, resolves the path token's invite, verifies the JWT (incl. its distinct
    `type`), and confirms its `token_id` matches the invite. Raises 401 (missing /
    invalid) / 403 (token_id mismatch), returning `(invite, payload)`.
    """

    async def _dependency(
        token: str,
        authorization: Optional[str] = Header(None),
        session_token: Optional[str] = Query(None, alias="session_token"),
    ) -> "ScreeningSession":
        invite = await get_screening_token_record(token)

        jwt_token = None
        if authorization and authorization.startswith("Bearer "):
            jwt_token = authorization[7:]
        elif session_token:
            jwt_token = session_token

        if not jwt_token:
            raise HTTPException(status_code=401, detail="Session token required")

        payload = verify_screening_session_token(jwt_token)
        if not payload:
            raise HTTPException(
                status_code=401, detail="Invalid or expired session token"
            )

        if payload.get("token_id") != invite["id"]:
            raise HTTPException(
                status_code=403, detail="Session token does not match screening link"
            )

        return invite, payload

    return _dependency


def _round_info(invite: dict) -> Tuple[Optional[str], Optional[str]]:
    """Pull (role_title, round_name) out of the joined invite record."""
    candidate_round = invite.get("candidate_rounds") or {}
    round_info = candidate_round.get("rounds") or {}
    requisition = round_info.get("requisitions") or {}
    return requisition.get("role_title"), round_info.get("name")


def _has_active_session(invite: dict) -> bool:
    session_expires_at = invite.get("session_expires_at")
    if not session_expires_at:
        return False
    exp = (
        parse_iso_datetime(session_expires_at)
        if isinstance(session_expires_at, str)
        else session_expires_at
    )
    return datetime.now(timezone.utc) < exp


@router.get("/{token}", response_model=ScreeningContextResponse)
async def get_screening_context(token: str):
    invite = await get_screening_token_record(token)
    role_title, round_name = _round_info(invite)
    has_active = _has_active_session(invite)
    return ScreeningContextResponse(
        role_title=role_title,
        round_name=round_name or "Screening",
        email_hint=mask_email(invite.get("candidate_email", "")),
        has_active_session=has_active,
    )


@router.post("/{token}/send-otp", response_model=ScreeningSendOTPResponse)
async def send_screening_otp(token: str):
    invite = await get_screening_token_record(token)
    otp_service = get_otp_service()
    screening_otp_service = get_screening_otp_service()

    # Defensive double-check (get_screening_token_record already 410s on expiry).
    if screening_otp_service.is_invite_expired(invite):
        raise HTTPException(status_code=410, detail="Screening link has expired")

    locked, locked_until = otp_service.is_locked(invite)
    if locked:
        minutes_remaining = (
            int((locked_until - datetime.now(timezone.utc)).total_seconds() / 60) + 1
        )
        return ScreeningSendOTPResponse(
            success=False,
            message=f"Too many failed attempts. Try again in {minutes_remaining} minutes.",
        )

    can_send, rate_limit_message = otp_service.can_send_otp(invite)
    if not can_send:
        return ScreeningSendOTPResponse(
            success=False,
            message=rate_limit_message,
            retry_after_seconds=60,
        )

    otp_code = otp_service.generate_otp()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=otp_service.OTP_VALIDITY_MINUTES)

    supabase = get_supabase_admin_client()
    await supabase.table("screening_invites").update(
        {
            "otp_code": otp_code,
            "otp_expires_at": expires_at.isoformat(),
            "otp_last_sent_at": now.isoformat(),
            "otp_attempts": 0,
            "otp_success_count": 0,
            "updated_at": now.isoformat(),
        }
    ).eq("id", invite["id"]).execute_async()

    candidate_email = invite["candidate_email"]
    role_title, round_name = _round_info(invite)
    candidate_name = candidate_email.split("@")[0].replace(".", " ").replace("_", " ").title()

    email_service = get_email_service()
    email_result = await email_service.send_templated_email(
        to_email=candidate_email,
        to_name=candidate_name,
        subject=f"Your verification code for the {role_title or 'screening'} screening",
        template_name="otp_email.html",
        context={
            "interviewer_name": candidate_name,
            "candidate_name": candidate_name,
            "round_name": round_name or "Screening",
            "otp_code": otp_code,
        },
    )

    if not email_result.success:
        logger.error(
            f"Failed to send OTP email for screening invite {invite['id']}: "
            f"{email_result.error}"
        )
        return ScreeningSendOTPResponse(
            success=False,
            message="Failed to send verification email. Please try again.",
        )

    logger.info(f"OTP generated and emailed for screening invite {invite['id']}")
    return ScreeningSendOTPResponse(
        success=True,
        message="Verification code sent to your email",
        email_hint=mask_email(candidate_email),
    )


@router.post("/{token}/verify-otp", response_model=ScreeningVerifyOTPResponse)
async def verify_screening_otp(token: str, request: ScreeningVerifyOTPRequest):
    invite = await get_screening_token_record(token)
    otp_service = get_otp_service()
    screening_otp_service = get_screening_otp_service()

    try:
        success, error_message = await screening_otp_service.verify_invite_otp(
            invite, request.otp
        )
    except InviteExpiredError:
        raise HTTPException(status_code=410, detail="Screening link has expired")

    if not success:
        invite_refreshed = await get_screening_token_record(token)
        locked, locked_until = otp_service.is_locked(invite_refreshed)
        current_attempts = invite_refreshed.get("otp_attempts", 0)
        attempts_remaining = max(0, otp_service.MAX_ATTEMPTS - current_attempts)
        return ScreeningVerifyOTPResponse(
            success=False,
            error=error_message,
            locked_until=locked_until.isoformat() if locked_until else None,
            attempts_remaining=attempts_remaining if not locked else 0,
        )

    session_token, session_expires_at = create_screening_session_token(
        token_id=invite["id"],
        candidate_email=invite["candidate_email"],
        candidate_round_id=invite["candidate_round_id"],
    )

    supabase = get_supabase_admin_client()
    now = datetime.now(timezone.utc).isoformat()
    await supabase.table("screening_invites").update(
        {
            "session_expires_at": session_expires_at.isoformat(),
            "last_accessed_at": now,
            "updated_at": now,
        }
    ).eq("id", invite["id"]).execute_async()

    logger.info(f"OTP verified, session created for screening invite {invite['id']}")
    return ScreeningVerifyOTPResponse(success=True, session_token=session_token)


@router.get("/{token}/session", response_model=ScreeningSessionResponse)
async def get_screening_session(
    token: str,
    session: ScreeningSession = Depends(require_screening_session()),
):
    invite, _ = session
    supabase = get_supabase_admin_client()
    await supabase.table("screening_invites").update(
        {"last_accessed_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", invite["id"]).execute_async()

    role_title, round_name = _round_info(invite)
    return ScreeningSessionResponse(
        valid=True,
        role_title=role_title,
        round_name=round_name or "Screening",
        candidate_email=invite.get("candidate_email"),
    )


@router.post("/{token}/start-voice", response_model=ScreeningStartVoiceResponse)
async def start_screening_voice(
    token: str,
    request: ScreeningStartVoiceRequest,
    _voice_enabled: None = Depends(require_voice_enabled),
    session: ScreeningSession = Depends(require_screening_session()),
):
    """Mint a voice-agent session token for the candidate screening call.

    VOICE_ENABLED 503 guard runs first (require_voice_enabled), then the session
    gate. The token write is a compare-and-set scoped by status so a concurrent /
    stale /start-voice can't clobber a freshly-minted token.
    """
    invite, _ = session
    candidate_round_id = invite["candidate_round_id"]
    supabase = get_supabase_admin_client()

    cr_result = await (
        supabase.table("candidate_rounds")
        .select("screening_voice_session_status")
        .eq("id", candidate_round_id)
        .single()
        .execute_async()
    )

    existing_status = (cr_result.data or {}).get("screening_voice_session_status")
    if existing_status in ("active", "completed") and not request.redo:
        raise HTTPException(
            status_code=409,
            detail=f"Voice screening session is already {existing_status}. "
            "Pass redo=true to start over.",
        )

    voice_session_token = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    update_payload: Dict[str, Any] = {
        "screening_voice_session_token": voice_session_token,
        "screening_voice_session_status": "pending",
        "screening_voice_session_started_at": now,
        "screening_voice_session_error": None,
        "updated_at": now,
    }

    # Atomic mint: only update when the status column still matches what we read.
    # If a concurrent /start-voice snuck in between read and write, this conditional
    # update affects zero rows and we 409 instead of clobbering the other token.
    mint_query = (
        supabase.table("candidate_rounds")
        .update(update_payload)
        .eq("id", candidate_round_id)
    )
    if existing_status is None:
        mint_query = mint_query.is_("screening_voice_session_status", "null")
    else:
        mint_query = mint_query.eq("screening_voice_session_status", existing_status)

    mint_result = await mint_query.execute_async()
    if not (mint_result.data or []):
        raise HTTPException(
            status_code=409,
            detail=(
                "Another voice screening session was started for this candidate "
                "at the same time. Please refresh and try again."
            ),
        )

    logger.info(
        f"Voice screening session minted for candidate_round {candidate_round_id} "
        f"(redo={request.redo})"
    )
    return ScreeningStartVoiceResponse(voice_session_token=voice_session_token)
