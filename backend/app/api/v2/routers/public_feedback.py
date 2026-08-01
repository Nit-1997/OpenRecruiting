import uuid
from datetime import datetime, timezone, timedelta
from typing import Callable, Optional, List, Dict, Any, Tuple
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel
from app.config import get_settings
from app.services.supabase import get_supabase_admin_client
from app.utils import parse_iso_datetime
from app.services.otp_service import get_otp_service
from app.services.email.service import get_email_service
from app.models.feedback import (
    FeedbackContextResponse,
    SendOTPResponse,
    VerifyOTPRequest,
    VerifyOTPResponse,
    FeedbackSessionResponse,
    FeedbackQuestion,
    StartVoiceRequest,
    StartVoiceResponse,
    QuestionSummary,
    FeedbackReviewResponse,
    FeedbackEditRequest,
    FeedbackEditResponse,
    FeedbackApproveResponse,
    FeedbackReprocessRequest,
    FeedbackReprocessResponse,
)
from difflib import SequenceMatcher
from app.services.feedback_job_service import get_feedback_job_service
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/public/feedback")


def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return "***@***"

    local, domain = email.rsplit("@", 1)
    if len(local) <= 1:
        masked_local = "*"
    elif len(local) <= 3:
        masked_local = local[0] + "***"
    else:
        masked_local = local[0] + "***"

    return f"{masked_local}@{domain}"


async def get_token_record(token: str, sync_email: bool = False) -> dict:
    supabase = get_supabase_admin_client()

    result = await supabase.table("feedback_access_tokens").select(
        "*, candidate_rounds!inner(id, scheduled_at, status, summary, rating, scorecard_transcript, interviewer_email, candidates!inner(id, name, email, requisition_id), rounds!inner(id, name, round_type))"
    ).eq("token", token).single().execute_async()

    if not result.data:
        raise HTTPException(status_code=404, detail="Invalid or expired feedback link")

    token_record = result.data

    expires_at_str = token_record.get("expires_at")
    if expires_at_str:
        if isinstance(expires_at_str, str):
            expires_at = parse_iso_datetime(expires_at_str)
        else:
            expires_at = expires_at_str

        if datetime.now(timezone.utc) > expires_at:
            raise HTTPException(status_code=410, detail="Feedback link has expired")

    if sync_email:
        round_email = token_record.get("candidate_rounds", {}).get("interviewer_email")
        token_email = token_record.get("interviewer_email")

        if round_email and round_email != token_email:
            await supabase.table("feedback_access_tokens").update({
                "interviewer_email": round_email,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "otp_code": None,
                "otp_expires_at": None,
                "otp_attempts": 0,
                "otp_success_count": 0,
                "otp_locked_until": None,
                "is_registered_user": None,
            }).eq("id", token_record["id"]).execute_async()

            logger.info(f"Synced token email from {token_email} to {round_email} for token {token_record['id']}")
            token_record["interviewer_email"] = round_email
            token_record["is_registered_user"] = None
            token_record["otp_code"] = None
            token_record["otp_expires_at"] = None
            token_record["otp_attempts"] = 0
            token_record["otp_success_count"] = 0
            token_record["otp_locked_until"] = None

    return token_record


# Verified session context shared by every session-gated endpoint:
# the resolved feedback token record plus the decoded session-JWT payload.
FeedbackSession = Tuple[dict, dict]


def require_feedback_session(
    missing_token_detail: str = "Session token required",
) -> Callable[..., "FeedbackSession"]:
    """Build a FastAPI dependency enforcing the feedback session-JWT gate.

    Extracts the session token from the `Authorization: Bearer` header or the
    `session_token` query param, resolves the path token's record, verifies the
    JWT, and confirms its `token_id` matches the path token. Raises 401 (missing
    or invalid token) / 403 (token_id mismatch) identically to the previously
    inlined gate, and returns `(token_record, payload)` for the handler.

    `missing_token_detail` is parameterized only because `/session` historically
    returned a longer "provide via Authorization header or session_token query
    parameter" message; every other endpoint used the short form.
    """

    async def _dependency(
        token: str,
        authorization: Optional[str] = Header(None),
        session_token: Optional[str] = Query(None, alias="session_token"),
    ) -> "FeedbackSession":
        token_record = await get_token_record(token)
        otp_service = get_otp_service()

        jwt_token = None
        if authorization and authorization.startswith("Bearer "):
            jwt_token = authorization[7:]
        elif session_token:
            jwt_token = session_token

        if not jwt_token:
            raise HTTPException(status_code=401, detail=missing_token_detail)

        payload = otp_service.verify_session_token(jwt_token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid or expired session token")

        if payload.get("token_id") != token_record["id"]:
            raise HTTPException(status_code=403, detail="Session token does not match feedback link")

        return token_record, payload

    return _dependency


def require_voice_enabled() -> None:
    """503 guard kept separate so it fires before the session gate (matches the
    original /start-voice ordering, where VOICE_ENABLED was checked first)."""
    settings = get_settings()
    if not settings.VOICE_ENABLED:
        raise HTTPException(status_code=503, detail="Voice feedback is not enabled.")


@router.get("/{token}", response_model=FeedbackContextResponse)
async def get_feedback_context(token: str):
    token_record = await get_token_record(token, sync_email=True)
    otp_service = get_otp_service()

    interviewer_email = token_record.get("interviewer_email")
    is_registered_user = token_record.get("is_registered_user")

    if is_registered_user is None:
        is_registered_user = await otp_service.is_interviewer_registered(interviewer_email)

        supabase = get_supabase_admin_client()
        await supabase.table("feedback_access_tokens").update({
            "is_registered_user": is_registered_user,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", token_record["id"]).execute_async()

    session_expires_at = token_record.get("session_expires_at")
    has_active_session = False
    if session_expires_at:
        if isinstance(session_expires_at, str):
            exp = parse_iso_datetime(session_expires_at)
        else:
            exp = session_expires_at
        has_active_session = datetime.now(timezone.utc) < exp

    candidate_round = token_record.get("candidate_rounds", {})
    candidate = candidate_round.get("candidates", {})
    round_info = candidate_round.get("rounds", {})

    requires_otp = not is_registered_user and not has_active_session
    requires_platform_login = is_registered_user and not has_active_session

    return FeedbackContextResponse(
        requires_otp=requires_otp,
        requires_platform_login=requires_platform_login,
        has_active_session=has_active_session,
        candidate_name=candidate.get("name"),
        round_name=round_info.get("name", "Interview"),
        email_hint=mask_email(interviewer_email) if requires_otp else None,
    )


@router.post("/{token}/send-otp", response_model=SendOTPResponse)
async def send_otp(token: str):
    token_record = await get_token_record(token, sync_email=True)
    otp_service = get_otp_service()

    is_registered_user = token_record.get("is_registered_user")
    if is_registered_user is None:
        is_registered_user = await otp_service.is_interviewer_registered(token_record["interviewer_email"])

    if is_registered_user:
        return SendOTPResponse(
            success=False,
            message="Please sign in with your OpenRecruiting account instead",
        )

    locked, locked_until = otp_service.is_locked(token_record)
    if locked:
        minutes_remaining = int((locked_until - datetime.now(timezone.utc)).total_seconds() / 60) + 1
        return SendOTPResponse(
            success=False,
            message=f"Too many failed attempts. Try again in {minutes_remaining} minutes.",
        )

    can_send, rate_limit_message = otp_service.can_send_otp(token_record)
    if not can_send:
        return SendOTPResponse(
            success=False,
            message=rate_limit_message,
            retry_after_seconds=60,
        )

    otp_code = otp_service.generate_otp()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=otp_service.OTP_VALIDITY_MINUTES)

    supabase = get_supabase_admin_client()
    await supabase.table("feedback_access_tokens").update({
        "otp_code": otp_code,
        "otp_expires_at": expires_at.isoformat(),
        "otp_last_sent_at": now.isoformat(),
        "otp_attempts": 0,
        "otp_success_count": 0,
        "updated_at": now.isoformat(),
    }).eq("id", token_record["id"]).execute_async()

    interviewer_email = token_record["interviewer_email"]
    candidate_round = token_record.get("candidate_rounds", {})
    candidate = candidate_round.get("candidates", {})
    round_info = candidate_round.get("rounds", {})

    candidate_name = candidate.get("name", "the candidate")
    round_name = round_info.get("name", "the interview")
    interviewer_name = interviewer_email.split("@")[0].replace(".", " ").replace("_", " ").title()

    email_service = get_email_service()
    email_result = await email_service.send_templated_email(
        to_email=interviewer_email,
        to_name=interviewer_name,
        subject=f"Your verification code for {candidate_name}'s feedback",
        template_name="otp_email.html",
        context={
            "interviewer_name": interviewer_name,
            "candidate_name": candidate_name,
            "round_name": round_name,
            "otp_code": otp_code,
        },
    )

    if not email_result.success:
        logger.error(f"Failed to send OTP email for feedback token {token_record['id']}: {email_result.error}")
        return SendOTPResponse(
            success=False,
            message="Failed to send verification email. Please try again.",
        )

    logger.info(f"OTP generated and emailed for feedback token {token_record['id']}")

    return SendOTPResponse(
        success=True,
        message="Verification code sent to your email",
        email_hint=mask_email(interviewer_email),
    )


@router.post("/{token}/verify-otp", response_model=VerifyOTPResponse)
async def verify_otp(token: str, request: VerifyOTPRequest):
    token_record = await get_token_record(token)
    otp_service = get_otp_service()

    is_registered_user = token_record.get("is_registered_user")
    if is_registered_user:
        return VerifyOTPResponse(
            success=False,
            error="Please sign in with your OpenRecruiting account instead",
        )

    success, error_message = await otp_service.verify_otp(token_record, request.otp)

    if not success:
        token_record_refreshed = await get_token_record(token)
        locked, locked_until = otp_service.is_locked(token_record_refreshed)

        current_attempts = token_record_refreshed.get("otp_attempts", 0)
        attempts_remaining = max(0, otp_service.MAX_ATTEMPTS - current_attempts)

        return VerifyOTPResponse(
            success=False,
            error=error_message,
            locked_until=locked_until.isoformat() if locked_until else None,
            attempts_remaining=attempts_remaining if not locked else 0,
        )

    session_token, session_expires_at = otp_service.create_session_token(
        token_id=token_record["id"],
        interviewer_email=token_record["interviewer_email"],
        candidate_round_id=token_record["candidate_round_id"],
    )

    supabase = get_supabase_admin_client()
    await supabase.table("feedback_access_tokens").update({
        "session_expires_at": session_expires_at.isoformat(),
        "last_accessed_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", token_record["id"]).execute_async()

    logger.info(f"OTP verified, session created for feedback token {token_record['id']}")

    return VerifyOTPResponse(
        success=True,
        session_token=session_token,
    )


@router.post("/{token}/openrecruiting-auth", response_model=VerifyOTPResponse)
async def platform_auth(
    token: str,
    authorization: Optional[str] = Header(None),
):
    """Authenticate a OpenRecruiting user and create session token."""
    import jwt
    from jwt.exceptions import InvalidTokenError as JWTError
    from app.dependencies import get_jwks_client
    from app.config import get_settings

    token_record = await get_token_record(token, sync_email=True)
    otp_service = get_otp_service()

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Supabase authorization required"
        )

    supabase_token = authorization[7:]

    try:
        unverified_header = jwt.get_unverified_header(supabase_token)
        alg = unverified_header.get("alg", "HS256")
        kid = unverified_header.get("kid")

        if alg == "ES256" and kid:
            jwks_client = get_jwks_client()
            jwk = await jwks_client.get_key(kid)
            if not jwk:
                raise HTTPException(status_code=401, detail="Unknown signing key")
            public_key = jwt.algorithms.ECAlgorithm.from_jwk(jwk)
            payload = jwt.decode(
                supabase_token,
                public_key,
                algorithms=["ES256"],
                audience="authenticated",
            )
        else:
            settings = get_settings()
            payload = jwt.decode(
                supabase_token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )

        user_email = payload.get("email")
        if not user_email:
            raise HTTPException(status_code=401, detail="Invalid token: no email")

    except JWTError as e:
        logger.error(f"Failed to verify Supabase token: {e}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    interviewer_email = token_record.get("interviewer_email", "").lower()
    if not user_email or user_email.lower() != interviewer_email:
        raise HTTPException(
            status_code=403,
            detail="Your email does not match the interviewer for this feedback request"
        )

    session_token, session_expires_at = otp_service.create_session_token(
        token_id=token_record["id"],
        interviewer_email=interviewer_email,
        candidate_round_id=token_record["candidate_round_id"],
    )

    supabase = get_supabase_admin_client()
    await supabase.table("feedback_access_tokens").update({
        "session_expires_at": session_expires_at.isoformat(),
        "last_accessed_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", token_record["id"]).execute_async()

    logger.info(f"OpenRecruiting auth successful, session created for feedback token {token_record['id']} by {user_email}")

    return VerifyOTPResponse(
        success=True,
        session_token=session_token,
    )


@router.get("/{token}/session", response_model=FeedbackSessionResponse)
async def get_feedback_session(
    token: str,
    session: FeedbackSession = Depends(
        require_feedback_session(
            "Session token required. Provide via Authorization header or session_token query parameter."
        )
    ),
):
    token_record, _ = session
    supabase = get_supabase_admin_client()
    await supabase.table("feedback_access_tokens").update({
        "last_accessed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", token_record["id"]).execute_async()

    candidate_round = token_record.get("candidate_rounds", {})
    candidate = candidate_round.get("candidates", {})
    round_info = candidate_round.get("rounds", {})

    has_transcript = bool(candidate_round.get("scorecard_transcript"))
    has_scorecard = bool(candidate_round.get("has_scorecard"))
    has_existing_feedback = bool(candidate_round.get("summary") or candidate_round.get("rating"))

    round_id = round_info.get("id")
    questions = None
    if round_id:
        questions_result = await supabase.table("feedback_questions").select(
            "question_number, heading, description"
        ).eq("round_id", round_id).is_null("deleted_at").order("question_number").execute_async()

        if questions_result.data:
            questions = [
                FeedbackQuestion(
                    question_number=q["question_number"],
                    heading=q["heading"],
                    description=q.get("description"),
                )
                for q in questions_result.data
            ]

    return FeedbackSessionResponse(
        candidate_name=candidate.get("name", "Unknown"),
        candidate_email=candidate.get("email", ""),
        round_name=round_info.get("name", "Interview"),
        round_type=round_info.get("round_type", "interview"),
        interview_date=candidate_round.get("scheduled_at"),
        has_transcript=has_transcript,
        has_scorecard=has_scorecard,
        existing_transcript=candidate_round.get("scorecard_transcript"),
        has_existing_feedback=has_existing_feedback,
        questions=questions,
    )


@router.post("/{token}/start-voice", response_model=StartVoiceResponse)
async def start_voice_feedback(
    token: str,
    request: StartVoiceRequest,
    _voice_enabled: None = Depends(require_voice_enabled),
    session: FeedbackSession = Depends(require_feedback_session()),
):
    """Mint a voice-agent session token for in-app feedback collection.

    Auth gate is identical to /session, /edit, etc. — accepts the OTP-issued
    JWT (external interviewer flow) OR the OpenRecruiting-auth-issued JWT (logged-in
    recruiter flow). Both converge here. The VOICE_ENABLED 503 guard runs first
    (via require_voice_enabled), matching the original ordering.
    """
    token_record, _ = session
    candidate_round_id = token_record["candidate_round_id"]
    supabase = get_supabase_admin_client()

    cr_result = await supabase.table("candidate_rounds").select(
        "feedback_voice_session_status"
    ).eq("id", candidate_round_id).single().execute_async()

    existing_status = (cr_result.data or {}).get("feedback_voice_session_status")
    if existing_status in ("active", "completed") and not request.redo:
        raise HTTPException(
            status_code=409,
            detail=f"Voice feedback session is already {existing_status}. Pass redo=true to start over.",
        )

    voice_session_token = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Only the session-tracking columns change here. Existing scorecard_transcript,
    # summary, rating, question_summaries, and processing_status are preserved so
    # that an abandoned or failed redo does not destroy previously-generated
    # feedback. The next successful voice-complete will overwrite them atomically
    # via /internal/feedback/voice-complete; if that completion never arrives,
    # the prior feedback remains intact.
    update_payload: Dict[str, Any] = {
        "feedback_voice_session_token": voice_session_token,
        "feedback_voice_session_status": "pending",
        "feedback_voice_session_started_at": now,
        "feedback_voice_session_error": None,
        "updated_at": now,
    }

    # Atomic mint: only update when the status column is still what we just
    # read. If a concurrent /start-voice (rapid double-click, two tabs) snuck
    # in between our read and write, the conditional update affects zero rows
    # and we return 409 so the caller can retry — instead of silently
    # overwriting the other caller's freshly-minted token.
    mint_query = (
        supabase.table("candidate_rounds")
        .update(update_payload)
        .eq("id", candidate_round_id)
    )
    if existing_status is None:
        mint_query = mint_query.is_("feedback_voice_session_status", "null")
    else:
        mint_query = mint_query.eq("feedback_voice_session_status", existing_status)

    mint_result = await mint_query.execute_async()
    if not (mint_result.data or []):
        raise HTTPException(
            status_code=409,
            detail=(
                "Another voice feedback session was started for this candidate "
                "at the same time. Please refresh and try again."
            ),
        )

    logger.info(
        f"Voice feedback session minted for candidate_round {candidate_round_id} "
        f"(redo={request.redo})"
    )

    return StartVoiceResponse(voice_session_token=voice_session_token)


@router.get("/{token}/review", response_model=FeedbackReviewResponse)
async def get_feedback_review(
    token: str,
    session: FeedbackSession = Depends(require_feedback_session()),
):
    """Get generated feedback for review."""
    token_record, _ = session
    candidate_round_id = token_record["candidate_round_id"]
    supabase = get_supabase_admin_client()

    cr_result = await supabase.table("candidate_rounds").select(
        "id, summary, rating, question_summaries, processing_status, scheduled_at, round_id, "
        "feedback_approved_at, feedback_approved_by_email, feedback_voice_session_status, "
        "feedback_voice_session_error"
    ).eq("id", candidate_round_id).single().execute_async()

    if not cr_result.data:
        raise HTTPException(status_code=404, detail="Candidate round not found")

    cr = cr_result.data

    questions_result = await supabase.table("feedback_questions").select(
        "id, question_number, heading, description"
    ).eq("round_id", cr["round_id"]).is_null("deleted_at").order("question_number").execute_async()

    raw_summaries = cr.get("question_summaries") or {}
    question_summaries = []
    for q in (questions_result.data or []):
        q_num = str(q["question_number"])
        question_summaries.append(QuestionSummary(
            question_number=q["question_number"],
            question_text=q.get("heading", ""),
            description=q.get("description"),
            summary=raw_summaries.get(q_num),
        ))

    candidate_round = token_record.get("candidate_rounds", {})
    candidate = candidate_round.get("candidates", {})
    round_info = candidate_round.get("rounds", {})

    return FeedbackReviewResponse(
        candidate_round_id=candidate_round_id,
        candidate_name=candidate.get("name", "Unknown"),
        round_name=round_info.get("name", "Interview"),
        interview_date=cr.get("scheduled_at"),
        processing_status=cr.get("processing_status", "pending"),
        summary=cr.get("summary"),
        rating=cr.get("rating"),
        question_summaries=question_summaries if question_summaries else None,
        can_edit=True,
        is_approved=cr.get("feedback_approved_at") is not None,
        approved_at=cr.get("feedback_approved_at"),
        feedback_voice_session_status=cr.get("feedback_voice_session_status"),
        feedback_voice_session_error=cr.get("feedback_voice_session_error"),
    )


@router.put("/{token}/edit", response_model=FeedbackEditResponse)
async def edit_feedback(
    token: str,
    request: FeedbackEditRequest,
    session: FeedbackSession = Depends(require_feedback_session()),
):
    """Edit/correct generated feedback."""
    token_record, _ = session
    candidate_round_id = token_record["candidate_round_id"]
    supabase = get_supabase_admin_client()

    update_data = {"updated_at": datetime.now(timezone.utc).isoformat()}

    if request.summary is not None:
        update_data["summary"] = request.summary

    if request.rating is not None:
        update_data["rating"] = request.rating

    if request.question_summaries is not None:
        cr_result = await supabase.table("candidate_rounds").select(
            "question_summaries"
        ).eq("id", candidate_round_id).single().execute_async()

        existing = (cr_result.data or {}).get("question_summaries") or {}
        merged = {**existing, **request.question_summaries}
        update_data["question_summaries"] = merged

    await supabase.table("candidate_rounds").update(update_data).eq(
        "id", candidate_round_id
    ).execute_async()

    logger.info(f"Feedback edited for candidate_round {candidate_round_id}")

    return FeedbackEditResponse(
        success=True,
        message="Feedback updated successfully",
    )


@router.post("/{token}/approve", response_model=FeedbackApproveResponse)
async def approve_feedback(
    token: str,
    session: FeedbackSession = Depends(require_feedback_session()),
):
    """Approve AI-generated feedback as accurate."""
    token_record, _ = session
    candidate_round_id = token_record["candidate_round_id"]
    interviewer_email = token_record.get("interviewer_email", "unknown")
    supabase = get_supabase_admin_client()

    now = datetime.now(timezone.utc)
    await supabase.table("candidate_rounds").update({
        "feedback_approved_at": now.isoformat(),
        "feedback_approved_by_email": interviewer_email,
        "updated_at": now.isoformat(),
    }).eq("id", candidate_round_id).execute_async()

    logger.info(f"Feedback approved for candidate_round {candidate_round_id} by {interviewer_email}")

    return FeedbackApproveResponse(
        success=True,
        message="Feedback approved successfully",
        approved_at=now.isoformat(),
    )


def is_significant_change(original: str, updated: str) -> bool:
    """Determine if edit warrants re-processing via Lambda."""
    if not original:
        return len(updated.split('\n')) >= 20

    original_lines = len(original.split('\n'))
    updated_lines = len(updated.split('\n'))

    if updated_lines - original_lines >= 20:
        return True

    similarity = SequenceMatcher(None, original, updated).ratio()
    if similarity < 0.5:
        return True

    return False


@router.post("/{token}/reprocess", response_model=FeedbackReprocessResponse)
async def reprocess_feedback(
    token: str,
    request: FeedbackReprocessRequest,
    session: FeedbackSession = Depends(require_feedback_session()),
):
    """Reprocess feedback through Lambda if significant changes detected."""
    token_record, _ = session
    candidate_round_id = token_record["candidate_round_id"]
    supabase = get_supabase_admin_client()

    cr_result = await supabase.table("candidate_rounds").select(
        "scorecard_transcript, summary"
    ).eq("id", candidate_round_id).single().execute_async()

    if not cr_result.data:
        raise HTTPException(status_code=404, detail="Candidate round not found")

    existing_transcript = cr_result.data.get("scorecard_transcript") or ""
    existing_summary = cr_result.data.get("summary") or ""

    combined_existing = f"{existing_transcript}\n\n{existing_summary}".strip()
    significant = is_significant_change(combined_existing, request.updated_transcript)

    if not significant:
        return FeedbackReprocessResponse(
            success=True,
            message="Changes are not significant enough to warrant reprocessing",
            reprocessing=False,
            processing_status="completed",
        )

    now = datetime.now(timezone.utc)
    await supabase.table("candidate_rounds").update({
        "scorecard_transcript": request.updated_transcript,
        "updated_at": now.isoformat(),
    }).eq("id", candidate_round_id).execute_async()

    feedback_service = get_feedback_job_service()
    try:
        result = await feedback_service.trigger_feedback_processing(
            candidate_round_id,
            skip_prereq_check=True
        )

        if result.get("status") == "accepted":
            logger.info(f"Feedback reprocessing triggered for candidate_round {candidate_round_id}")
            return FeedbackReprocessResponse(
                success=True,
                message="Significant changes detected. Reprocessing feedback...",
                reprocessing=True,
                processing_status="processing",
            )
        else:
            return FeedbackReprocessResponse(
                success=True,
                message="Feedback saved but reprocessing could not start",
                reprocessing=False,
                processing_status="pending",
            )
    except Exception as e:
        logger.error(f"Failed to trigger feedback reprocessing for round {candidate_round_id}: {e}")
        return FeedbackReprocessResponse(
            success=True,
            message="Feedback saved but reprocessing failed to start",
            reprocessing=False,
            processing_status="pending",
        )


class ValidateSessionRequest(BaseModel):
    session_token: str


@router.post("/validate-session")
async def validate_feedback_session(request: ValidateSessionRequest):
    otp_service = get_otp_service()
    payload = otp_service.verify_session_token(request.session_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return {"valid": True}
