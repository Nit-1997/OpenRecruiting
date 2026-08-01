from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Literal

from app.config import get_settings
from app.logging_config import get_logger
from app.services.calendar_intelligence_service import resolve_candidate_name, resolve_interviewer_email
from app.services.supabase import insert_many

logger = get_logger(__name__)

GENERIC_TEMPLATE_CONFIG = {
    "template_key": "GLOBAL_UNTRACKED_INTERVIEW_V1",
    "requisition_title": "Untracked Interviews",
    "requisition_location": "Hidden System Template",
    "round_name": "Generic Interview",
    "duration_minutes": 45,
    "questions": [
        {
            "question_number": 1,
            "heading": "Technical Competency",
            "description": "Evaluate the candidate's technical knowledge and problem-solving ability.",
        },
        {
            "question_number": 2,
            "heading": "Communication Skills",
            "description": "Assess clarity of explanation, listening skills, and ability to articulate ideas.",
        },
        {
            "question_number": 3,
            "heading": "Problem Approach",
            "description": "Evaluate how the candidate structures their thinking and approaches problems.",
        },
        {
            "question_number": 4,
            "heading": "Overall Impression",
            "description": "General assessment of candidate fit, enthusiasm, and professionalism.",
        },
    ],
}


@dataclass
class UntrackedCaptureResult:
    candidate_id: str
    candidate_round_id: str
    candidate_name: str
    candidate_email: str
    requisition_id: str
    round_id: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_unique_violation(exc: Exception) -> bool:
    message = str(exc).lower()
    return "duplicate key" in message or "unique" in message


def _first_row(data: Any) -> Optional[dict]:
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        return data
    return None


def _candidate_email_from_detection(detection: dict) -> str:
    for attendee in (detection.get("external_attendees") or []):
        email = str(attendee.get("email") or "").strip().lower()
        if email:
            return email
    return ""


def _candidate_name_from_detection(detection: dict, candidate_email: str) -> str:
    if candidate_email:
        try:
            name = resolve_candidate_name(detection, candidate_email)
            if name:
                return name
        except Exception:
            pass

    for attendee in (detection.get("external_attendees") or []):
        name = str(attendee.get("display_name") or "").strip()
        if name:
            return name

    signals = detection.get("detection_signals") or {}
    if isinstance(signals, dict):
        classification = signals.get("classification")
        if isinstance(classification, dict):
            name = str(classification.get("candidate_name") or "").strip()
            if name:
                return name

    return "Unknown Candidate"


def _interviewer_email_from_detection(detection: dict) -> Optional[str]:
    try:
        return resolve_interviewer_email(
            detection.get("internal_attendees") or [],
            None,
            "",
        )
    except Exception:
        return None


def _is_missing_auto_join_untracked_column_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "auto_join_untracked" in message
        and ("column" in message or "does not exist" in message or "schema cache" in message)
    )


async def _is_org_auto_join_untracked_enabled(supabase, organization_id: str) -> bool:
    org_result = await supabase.table("organizations") \
        .select("auto_join_untracked") \
        .eq("id", organization_id) \
        .limit(1) \
        .execute_async()

    row = _first_row(org_result.data)
    if not row:
        return False
    return bool(row.get("auto_join_untracked"))


async def get_auto_join_untracked_preference(
    supabase,
    *,
    profile_id: str,
    organization_id: str | None = None,
) -> tuple[bool, str]:
    profile_id = str(profile_id or "").strip()
    organization_id = str(organization_id or "").strip()
    if not profile_id:
        return False, "missing_profile_id"

    try:
        conn_result = await supabase.table("user_connections") \
            .select("auto_join_untracked") \
            .eq("profile_id", profile_id) \
            .eq("provider", "google_calendar") \
            .eq("is_active", True) \
            .limit(1) \
            .execute_async()
    except Exception as exc:
        if organization_id and _is_missing_auto_join_untracked_column_error(exc):
            org_enabled = await _is_org_auto_join_untracked_enabled(supabase, organization_id)
            source = "organization_fallback_enabled" if org_enabled else "organization_fallback_disabled"
            return org_enabled, source
        raise

    conn_row = _first_row(conn_result.data)
    if not conn_row:
        return False, "missing_user_connection"

    return bool(conn_row.get("auto_join_untracked")), "user_connection"


async def is_auto_join_untracked_enabled(
    supabase,
    organization_id: str,
    profile_id: str | None = None,
) -> bool:
    if profile_id:
        enabled, _ = await get_auto_join_untracked_preference(
            supabase,
            profile_id=profile_id,
            organization_id=organization_id,
        )
        return enabled
    return await _is_org_auto_join_untracked_enabled(supabase, organization_id)


def is_untracked_capture_enabled() -> bool:
    """Global kill-switch for generic untracked capture bot scheduling."""
    try:
        return bool(get_settings().CALENDAR_INTELLIGENCE_UNTRACKED_BOT_ENABLED)
    except Exception:
        return True


async def _get_binding(supabase, organization_id: str) -> Optional[dict]:
    result = await supabase.table("org_generic_template_bindings") \
        .select("id, organization_id, template_key, materialized_requisition_id, materialized_round_id") \
        .eq("organization_id", organization_id) \
        .eq("template_key", GENERIC_TEMPLATE_CONFIG["template_key"]) \
        .limit(1) \
        .execute_async()
    return _first_row(result.data)


async def _cleanup_orphan_materialization(
    supabase,
    requisition_id: Optional[str],
    round_id: Optional[str],
) -> None:
    if not requisition_id and not round_id:
        return

    now = _now_iso()

    try:
        if round_id:
            await supabase.table("feedback_questions") \
                .update({"deleted_at": now, "updated_at": now}) \
                .eq("round_id", round_id) \
                .is_("deleted_at", "null") \
                .execute_async()

            await supabase.table("rounds") \
                .update({"deleted_at": now, "updated_at": now}) \
                .eq("id", round_id) \
                .is_("deleted_at", "null") \
                .execute_async()

        if requisition_id:
            await supabase.table("requisitions") \
                .update({"deleted_at": now, "updated_at": now}) \
                .eq("id", requisition_id) \
                .is_("deleted_at", "null") \
                .execute_async()
    except Exception as cleanup_exc:
        logger.warning(
            "untracked_capture.materialization_cleanup_failed",
            extra={
                "requisition_id": requisition_id,
                "round_id": round_id,
                "error": str(cleanup_exc)[:150],
            },
        )


async def resolve_or_materialize_binding(supabase, organization_id: str) -> dict:
    existing = await _get_binding(supabase, organization_id)
    if existing:
        return existing

    created_requisition_id: Optional[str] = None
    created_round_id: Optional[str] = None

    req_result = await supabase.table("requisitions") \
        .insert({
            "organization_id": organization_id,
            "role_title": GENERIC_TEMPLATE_CONFIG["requisition_title"],
            "role_location": GENERIC_TEMPLATE_CONFIG["requisition_location"],
            "status": "planned",
            "is_system_template": True,
            "template_key": GENERIC_TEMPLATE_CONFIG["template_key"],
            "created_by": None,
        }) \
        .execute_async()
    req_row = _first_row(req_result.data)
    if not req_row:
        raise RuntimeError("Failed to create generic requisition")

    created_requisition_id = str(req_row["id"])

    round_result = await supabase.table("rounds") \
        .insert({
            "requisition_id": created_requisition_id,
            "round_number": 1,
            "name": GENERIC_TEMPLATE_CONFIG["round_name"],
            "duration_minutes": GENERIC_TEMPLATE_CONFIG["duration_minutes"],
            "category": "generic",
            "description": "System-managed generic interview capture round",
            "skills": [],
            "guidelines": [],
            "round_type": "interview",
            "default_interviewer_emails": [],
        }) \
        .execute_async()
    round_row = _first_row(round_result.data)
    if not round_row:
        raise RuntimeError("Failed to create generic round")

    created_round_id = str(round_row["id"])

    question_rows = [
        {
            "round_id": created_round_id,
            "question_number": q["question_number"],
            "heading": q["heading"],
            "description": q["description"],
        }
        for q in GENERIC_TEMPLATE_CONFIG["questions"]
    ]
    if question_rows:
        await insert_many(supabase, "feedback_questions", question_rows).execute_async()

    try:
        binding_result = await supabase.table("org_generic_template_bindings") \
            .insert({
                "organization_id": organization_id,
                "template_key": GENERIC_TEMPLATE_CONFIG["template_key"],
                "materialized_requisition_id": created_requisition_id,
                "materialized_round_id": created_round_id,
            }) \
            .execute_async()
        binding_row = _first_row(binding_result.data)
        if not binding_row:
            raise RuntimeError("Failed to create org generic template binding")

        logger.info(
            "untracked_capture.materialized",
            extra={
                "org_id": organization_id,
                "requisition_id": created_requisition_id,
                "round_id": created_round_id,
            },
        )
        return binding_row
    except Exception as binding_exc:
        if not _is_unique_violation(binding_exc):
            raise

        existing = await _get_binding(supabase, organization_id)
        if existing:
            await _cleanup_orphan_materialization(
                supabase,
                created_requisition_id,
                created_round_id,
            )
            logger.info(
                "untracked_capture.materialization_race",
                extra={
                    "org_id": organization_id,
                    "template_key": GENERIC_TEMPLATE_CONFIG["template_key"],
                },
            )
            return existing
        raise


async def _create_or_reuse_generic_candidate(
    supabase,
    materialized_requisition_id: str,
    detection: dict,
) -> tuple[dict, bool]:
    detection_id = str(detection.get("id"))
    candidate_email = _candidate_email_from_detection(detection)
    candidate_name = _candidate_name_from_detection(detection, candidate_email)

    if not candidate_email:
        candidate_email = f"unknown+{detection_id}@untracked.local"

    existing = await supabase.table("candidates") \
        .select("id, name, email") \
        .eq("requisition_id", materialized_requisition_id) \
        .eq("email", candidate_email) \
        .is_("deleted_at", "null") \
        .limit(1) \
        .execute_async()
    existing_row = _first_row(existing.data)
    if existing_row:
        logger.info(
            "untracked_capture.candidate_reused",
            extra={
                "candidate_id": existing_row.get("id"),
                "email": existing_row.get("email"),
                "detection_id": detection_id,
            },
        )
        return existing_row, False

    candidate_payload = {
        "requisition_id": materialized_requisition_id,
        "name": candidate_name,
        "email": candidate_email,
        "status": "active",
    }

    try:
        candidate_result = await supabase.table("candidates") \
            .insert(candidate_payload) \
            .execute_async()
    except Exception as exc:
        if not _is_unique_violation(exc):
            raise

        recheck = await supabase.table("candidates") \
            .select("id, name, email") \
            .eq("requisition_id", materialized_requisition_id) \
            .eq("email", candidate_email) \
            .is_("deleted_at", "null") \
            .limit(1) \
            .execute_async()
        row = _first_row(recheck.data)
        if row:
            logger.info(
                "untracked_capture.candidate_reused",
                extra={
                    "candidate_id": row.get("id"),
                    "email": row.get("email"),
                    "detection_id": detection_id,
                },
            )
            return row, False
        raise

    created_row = _first_row(candidate_result.data)
    if not created_row:
        raise RuntimeError("Failed to create generic candidate")

    logger.info(
        "untracked_capture.candidate_created",
        extra={
            "candidate_id": created_row.get("id"),
            "email": created_row.get("email"),
            "detection_id": detection_id,
        },
    )
    return created_row, True


async def _create_or_reuse_generic_candidate_round(
    supabase,
    candidate_id: str,
    materialized_round_id: str,
    detection: dict,
) -> tuple[str, bool]:
    detection_id = str(detection.get("id") or "")
    interviewer_email = _interviewer_email_from_detection(detection)

    payload = {
        "candidate_id": candidate_id,
        "round_id": materialized_round_id,
        "status": "scheduled",
        "meeting_url": detection.get("meeting_url"),
        "scheduled_at": detection.get("event_start"),
        "source_type": "untracked_generic",
        "origin_detection_id": detection.get("id"),
    }
    if interviewer_email:
        payload["interviewer_email"] = interviewer_email

    try:
        created = await supabase.table("candidate_rounds").insert(payload).execute_async()
        row = _first_row(created.data)
        if not row:
            raise RuntimeError("Failed to create generic candidate round")
        return str(row["id"]), True
    except Exception as exc:
        if not _is_unique_violation(exc):
            raise

        if detection_id:
            same_detection = await supabase.table("candidate_rounds") \
                .select("id, origin_detection_id") \
                .eq("source_type", "untracked_generic") \
                .eq("origin_detection_id", detection_id) \
                .limit(1) \
                .execute_async()
            row = _first_row(same_detection.data)
            if row:
                return str(row["id"]), False

        # Fallback safety check for pre-migration schemas that still enforce
        # unique(candidate_id, round_id) globally. Reusing a row created by a
        # different detection merges distinct interviews and loses provenance.
        existing = await supabase.table("candidate_rounds") \
            .select("id, origin_detection_id") \
            .eq("candidate_id", candidate_id) \
            .eq("round_id", materialized_round_id) \
            .limit(1) \
            .execute_async()
        row = _first_row(existing.data)
        if row:
            existing_origin = str(row.get("origin_detection_id") or "")
            if detection_id and existing_origin and existing_origin != detection_id:
                # Pre-migration fallback: if the DB still enforces a global
                # unique(candidate_id, round_id), create a detection-scoped
                # synthetic candidate so each detection still gets a unique
                # candidate_round record.
                candidate_result = await supabase.table("candidates") \
                    .select("id, requisition_id, name") \
                    .eq("id", candidate_id) \
                    .is_("deleted_at", "null") \
                    .limit(1) \
                    .execute_async()
                candidate_row = _first_row(candidate_result.data)
                if not candidate_row:
                    raise RuntimeError("Untracked capture round conflict and candidate lookup failed.")

                fallback_email = f"unknown+{detection_id}@untracked.local"
                fallback_candidate_payload = {
                    "requisition_id": candidate_row.get("requisition_id"),
                    "name": candidate_row.get("name") or "Unknown Candidate",
                    "email": fallback_email,
                    "status": "active",
                }

                fallback_candidate_id: Optional[str] = None
                try:
                    fallback_insert = await supabase.table("candidates") \
                        .insert(fallback_candidate_payload) \
                        .execute_async()
                    fallback_row = _first_row(fallback_insert.data)
                    if fallback_row:
                        fallback_candidate_id = str(fallback_row.get("id") or "")
                except Exception as candidate_exc:
                    if not _is_unique_violation(candidate_exc):
                        raise

                if not fallback_candidate_id:
                    fallback_lookup = await supabase.table("candidates") \
                        .select("id") \
                        .eq("requisition_id", str(candidate_row.get("requisition_id"))) \
                        .eq("email", fallback_email) \
                        .is_("deleted_at", "null") \
                        .limit(1) \
                        .execute_async()
                    fallback_row = _first_row(fallback_lookup.data)
                    fallback_candidate_id = str(fallback_row.get("id") or "") if fallback_row else ""

                if not fallback_candidate_id:
                    raise RuntimeError("Untracked capture conflict fallback candidate creation failed.")

                fallback_payload = dict(payload)
                fallback_payload["candidate_id"] = fallback_candidate_id
                fallback_insert_round = await supabase.table("candidate_rounds") \
                    .insert(fallback_payload) \
                    .execute_async()
                fallback_round_row = _first_row(fallback_insert_round.data)
                if not fallback_round_row:
                    raise RuntimeError("Untracked capture conflict fallback round creation failed.")
                return str(fallback_round_row["id"]), True
            if existing_origin == detection_id:
                return str(row["id"]), False
        raise


async def capture_untracked_interview(
    supabase,
    detection: dict,
    bot_linker: Callable[[str, str, Any], Awaitable[bool]],
) -> Optional[UntrackedCaptureResult]:
    return await materialize_untracked_capture(
        supabase,
        detection,
        bot_linker,
        capture_mode="confirmed",
        finalize_detection=True,
    )


async def materialize_untracked_capture(
    supabase,
    detection: dict,
    bot_linker: Callable[[str, str, Any], Awaitable[bool]],
    *,
    capture_mode: Literal["preconfirm", "confirmed"] = "preconfirm",
    finalize_detection: bool = False,
) -> Optional[UntrackedCaptureResult]:
    detection_id = str(detection.get("id"))
    organization_id = str(detection.get("organization_id"))
    current_step = "start"

    candidate_round_id: Optional[str] = None
    created_round = False

    try:
        logger.info(
            "untracked_capture.started",
            extra={
                "detection_id": detection_id,
                "org_id": organization_id,
                "event_title": detection.get("event_title", ""),
                "mode": capture_mode,
                "finalize_detection": finalize_detection,
            },
        )

        current_step = "resolve_binding"
        binding = await resolve_or_materialize_binding(supabase, organization_id)
        materialized_req_id = str(binding["materialized_requisition_id"])
        materialized_round_id = str(binding["materialized_round_id"])

        current_step = "candidate"
        candidate_row, _ = await _create_or_reuse_generic_candidate(
            supabase,
            materialized_req_id,
            detection,
        )
        candidate_id = str(candidate_row["id"])

        current_step = "candidate_round"
        candidate_round_id, created_round = await _create_or_reuse_generic_candidate_round(
            supabase,
            candidate_id,
            materialized_round_id,
            detection,
        )

        if created_round:
            logger.info(
                "untracked_capture.round_created",
                extra={
                    "candidate_round_id": candidate_round_id,
                    "detection_id": detection_id,
                },
            )

            current_step = "bot_deploy"
            bot_linked = await bot_linker(detection_id, candidate_round_id, supabase)
            if not bot_linked:
                now = _now_iso()
                await supabase.table("candidate_rounds") \
                    .update({"status": "cancelled", "updated_at": now}) \
                    .eq("id", candidate_round_id) \
                    .in_("status", ["pending", "scheduled"]) \
                    .execute_async()
                logger.error(
                    "untracked_capture.failed",
                    extra={
                        "detection_id": detection_id,
                        "org_id": organization_id,
                        "step": "bot_deploy",
                        "error": "bot_link_failed",
                    },
                )
                return None

            logger.info(
                "untracked_capture.bot_deployed",
                extra={
                    "candidate_round_id": candidate_round_id,
                    "detection_id": detection_id,
                },
            )

        current_step = "link_detection"
        existing_signals = detection.get("detection_signals") or {}
        if not isinstance(existing_signals, dict):
            existing_signals = {}

        candidate_name = str(candidate_row.get("name") or "Unknown Candidate")
        candidate_email = str(candidate_row.get("email") or "")

        existing_signals.update({
            "untracked_capture": True,
            "untracked_capture_template_key": GENERIC_TEMPLATE_CONFIG["template_key"],
            "untracked_capture_candidate_name": candidate_name,
            "untracked_capture_candidate_email": candidate_email,
            "untracked_capture_captured_at": _now_iso(),
        })
        if capture_mode == "preconfirm":
            existing_signals["untracked_capture_mode"] = "preconfirm"
            existing_signals["untracked_precapture_candidate_round_id"] = candidate_round_id
        else:
            existing_signals["untracked_capture_mode"] = "confirmed"
            existing_signals.pop("untracked_precapture_candidate_round_id", None)

        now = _now_iso()
        detection_update = {
            "matched_candidate_id": candidate_id,
            "matched_candidate_round_id": candidate_round_id,
            "detection_signals": existing_signals,
            "updated_at": now,
        }
        if finalize_detection:
            detection_update["detection_status"] = "confirmed"
            detection_update["responded_at"] = now

        await supabase.table("calendar_event_detections") \
            .update(detection_update) \
            .eq("id", detection_id) \
            .execute_async()

        logger.info(
            "untracked_capture.detection_linked",
            extra={
                "detection_id": detection_id,
                "candidate_id": candidate_id,
                "candidate_round_id": candidate_round_id,
            },
        )

        return UntrackedCaptureResult(
            candidate_id=candidate_id,
            candidate_round_id=candidate_round_id,
            candidate_name=candidate_name,
            candidate_email=candidate_email,
            requisition_id=materialized_req_id,
            round_id=materialized_round_id,
        )
    except Exception as exc:
        logger.error(
            "untracked_capture.failed",
            extra={
                "detection_id": detection_id,
                "org_id": organization_id,
                "step": current_step,
                "error": str(exc)[:150],
            },
            exc_info=True,
        )

        if candidate_round_id and created_round:
            try:
                await supabase.table("candidate_rounds") \
                    .update({"status": "cancelled", "updated_at": _now_iso()}) \
                    .eq("id", candidate_round_id) \
                    .in_("status", ["pending", "scheduled"]) \
                    .execute_async()
            except Exception:
                pass

        return None
