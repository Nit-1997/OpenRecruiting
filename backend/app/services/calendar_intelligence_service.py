import re
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo
import httpx
from app.config import get_settings
from app.logging_config import get_logger
from app.services.cal_intel.policy import VALID_TRANSITIONS
from app.services.cal_intel.matching import (  # re-exported for back-compat
    IANA_TIMEZONE_BY_LOWER,
    LOCATION_SIMILARITY_THRESHOLD,
    MAX_NARROWED_SCORE_HINTS,
    MULTI_EMAIL_AFFINITY_BOOST,
    ROLE_SIMILARITY_THRESHOLD,
    ROUND_SIMILARITY_THRESHOLD,
    _attendee_name_hints,
    _best_title_name_match,
    _canonical_location,
    _coerce_timezone_name,
    _description_overlap_ratio,
    _email_local_hints,
    _email_local_to_name,
    _extract_candidate_from_title,
    _extract_candidate_name_from_title,
    _extract_emails_from_text,
    _extract_interviewer_from_title,
    _extract_interviewer_name_from_title,
    _extract_title_name_candidates,
    _format_created_date,
    _format_event_time,
    _fuzzy_round_match,
    _internal_name_hints,
    _is_short_prefixed_role,
    _location_similarity,
    _name_hint_score,
    _normalize_person_name,
    _role_similarity,
    _role_tokens,
    _similarity,
    _text_tokens,
    email_affinity_lookup,
    filter_requisitions_by_extracted_fields,
    format_event_time_for_email,
    score_role_match,
)
from app.services.cal_intel.blocks import (  # re-exported for back-compat
    _DEFAULT_CONTEXT_NOT_SET,
    _DEFAULT_CONTEXT_UNKNOWN,
    _INTERACTION_STEP_LABELS,
    _STATUS_TO_INTERACTION_STEP,
    _add_role_url,
    _append_card_footer,
    _build_context_header,
    _coalesce_text,
    _display_value,
    _format_meeting_platform,
    _interaction_step_label,
    _resolve_display_timezone,
    _role_label,
    _role_option_label,
    _status_to_interaction_step,
    build_attendee_change_blocks,
    build_confirmation_blocks,
    build_detection_blocks,
    build_error_blocks,
    build_guidelines_html,
    build_interaction_context,
    build_app_action_url,
    build_no_req_blocks,
    build_open_in_app_action_block,
    build_open_in_app_button,
    build_reminder_blocks,
    build_reschedule_blocks,
    build_review_blocks,
    build_role_action_buttons,
    build_role_modal,
    build_role_selection_actions_block,
    build_role_selection_blocks,
    build_role_selection_step_blocks,
    build_round_selection_blocks,
    build_untracked_captured_blocks,
    merge_interaction_context,
)
from app.services.supabase import get_supabase_admin_client
from app.utils import parse_json_response

logger = get_logger(__name__)

VIDEO_PLATFORMS = {
    "meet.google.com": "google_meet",
    "zoom.us": "zoom",
    "teams.microsoft.com": "teams",
    "webex.com": "webex",
}



def transition_detection_status(current: str, new: str) -> str:
    valid = VALID_TRANSITIONS.get(current, set())
    if new not in valid:
        raise ValueError(
            f"Invalid status transition: {current} -> {new}. "
            f"Valid transitions from '{current}': {valid}"
        )
    return new


























def extract_meeting_url(event: dict) -> Optional[str]:
    raw = event.get("raw", {})
    conference = raw.get("conferenceData", {})
    for entry in conference.get("entryPoints", []):
        if entry.get("entryPointType") == "video":
            return entry.get("uri")

    location = raw.get("location", "")
    for domain in VIDEO_PLATFORMS:
        if domain in location:
            return location

    description = raw.get("description", "") or ""
    for domain in VIDEO_PLATFORMS:
        match = re.search(rf'https?://[^\s]*{re.escape(domain)}[^\s"<>]*', description)
        if match:
            return match.group(0)

    return None


def detect_meeting_platform(url: str) -> Optional[str]:
    if not url:
        return None
    for domain, platform in VIDEO_PLATFORMS.items():
        if domain in url:
            return platform
    return None


def extract_attendees(event: dict, org_domain: str) -> tuple[list[dict], list[dict]]:
    raw = event.get("raw", {})
    attendees = raw.get("attendees", [])
    external = []
    internal = []
    for att in attendees:
        email = att.get("email", "")
        if not email:
            continue
        entry = {
            "email": email,
            "display_name": att.get("displayName", ""),
            "response_status": att.get("responseStatus", ""),
            "organizer": att.get("organizer", False),
            "self": att.get("self", False),
        }
        domain = email.split("@")[-1].lower() if "@" in email else ""
        if domain == org_domain.lower():
            internal.append(entry)
        else:
            external.append(entry)
    return external, internal


def analyze_event(event: dict, org_domain: str) -> Optional[dict]:
    raw = event.get("raw", {})

    meeting_url = extract_meeting_url(event)
    if not meeting_url:
        return None

    external, internal = extract_attendees(event, org_domain)
    if not external:
        return None

    total_attendees = len(external) + len(internal)
    if total_attendees < 2 or total_attendees > 5:
        return None

    if raw.get("recurringEventId"):
        return None

    start_str = raw.get("start", {}).get("dateTime")
    end_str = raw.get("end", {}).get("dateTime")
    event_timezone = (
        raw.get("start", {}).get("timeZone")
        or raw.get("end", {}).get("timeZone")
        or raw.get("timeZone")
        or raw.get("timezone")
        or event.get("timeZone")
        or event.get("timezone")
        or event.get("time_zone")
    )
    if not start_str or not end_str:
        return None

    try:
        start = datetime.fromisoformat(start_str)
        end = datetime.fromisoformat(end_str)
        if start.tzinfo is None:
            tz_name = _coerce_timezone_name(str(event_timezone or ""))
            if tz_name:
                try:
                    start = start.replace(tzinfo=ZoneInfo(tz_name))
                    event_timezone = tz_name
                except Exception:
                    start = start.replace(tzinfo=timezone.utc)
            else:
                start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            tz_name = _coerce_timezone_name(str(event_timezone or ""))
            if tz_name:
                try:
                    end = end.replace(tzinfo=ZoneInfo(tz_name))
                    event_timezone = tz_name
                except Exception:
                    end = end.replace(tzinfo=timezone.utc)
            else:
                end = end.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None

    duration_minutes = (end - start).total_seconds() / 60
    if duration_minutes < 20 or duration_minutes > 90:
        return None

    return {
        "event_title": raw.get("summary", ""),
        "event_start": start,
        "event_end": end,
        "event_timezone": event_timezone,
        "meeting_url": meeting_url,
        "meeting_platform": detect_meeting_platform(meeting_url),
        "external_attendees": external,
        "internal_attendees": internal,
        "duration_minutes": duration_minutes,
        # Recall normalizes provider event identity at the top level. Keep the
        # historical `platform_event_id` key for backwards compatibility with
        # existing rows and tests while also exposing canonical fields.
        "platform_id": event.get("platform_id") or raw.get("id"),
        "ical_uid": event.get("ical_uid") or raw.get("iCalUID") or raw.get("icalUID"),
        "platform_event_id": event.get("platform_id") or raw.get("id"),
        "description": raw.get("description", ""),
        "location": raw.get("location", ""),
    }


# --- Interview Classification + Field Extraction (single LLM call) ---

async def llm_classify_and_extract(analyzed: dict) -> Optional[dict]:
    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        return None

    title = analyzed.get("event_title") or ""
    location = analyzed.get("location") or ""
    platform = analyzed.get("meeting_platform") or "video call"
    duration = analyzed.get("duration_minutes") or 0
    description = (analyzed.get("description") or "").replace("\x00", "").strip()
    description = re.sub(r"\s+", " ", description)[:4000]

    ext_list = ", ".join(
        f'{a.get("display_name") or "?"} ({a.get("email", "?")})'
        for a in (analyzed.get("external_attendees") or [])
    )
    int_list = ", ".join(
        f'{a.get("display_name") or "?"} ({a.get("email", "?")})'
        for a in (analyzed.get("internal_attendees") or [])
    )

    lines = [
        "Analyze this calendar event from a recruiter's calendar.",
        "Determine if it's a job interview and extract structured fields.",
        "",
        "Event:",
        f'- Title: "{title}"',
    ]
    if location:
        lines.append(f'- Location: "{location}"')
    lines.append(f'- Platform: {platform}')
    lines.append(f'- Duration: {duration} minutes')
    if description:
        lines.append(f'- Description: "{description}"')
    lines.extend([
        f'- External attendees: {ext_list or "none"}',
        f'- Internal attendees: {int_list or "none"}',
        "",
        "Strong interview signals (in order of importance):",
        "- External person meeting with internal person(s) on a video call",
        "- Job role or position title mentioned in event title",
        '- Common interview naming: "Name <> Name", "Name | Role", "Name - Role"',
        "- Duration typical for interviews (30-60 min)",
        "",
        "Return JSON only:",
        "{",
        '  "is_interview": true or false,',
        '  "confidence": 0.0 to 1.0,',
        '  "reasoning": "one line explanation",',
        '  "role_name": "job title if present, null if unclear",',
        '  "round_name": "interview round/stage if present, null if unclear",',
        '  "candidate_name": "candidate name if identifiable, null if unclear",',
        '  "location": "city/location if present, null if unclear"',
        "}",
    ])
    prompt = "\n".join(lines)

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.ANTHROPIC_API_KEY,
                        "content-type": "application/json",
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": settings.CALENDAR_INTELLIGENCE_MODEL,
                        "max_tokens": 200,
                        "temperature": 0,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                response.raise_for_status()
                resp_json = response.json()
                content = resp_json["content"][0]["text"]
                parsed = parse_json_response(content)
                if not isinstance(parsed, dict):
                    return None
                is_interview = parsed.get("is_interview")
                if not isinstance(is_interview, bool):
                    is_interview = str(is_interview).lower() in ("true", "1", "yes")
                try:
                    conf = float(parsed.get("confidence", 0))
                except (ValueError, TypeError):
                    conf = 0.0
                conf = max(0.0, min(1.0, conf))
                return {
                    "is_interview": is_interview,
                    "confidence": conf,
                    "reasoning": str(parsed.get("reasoning") or ""),
                    "role_name": str(parsed["role_name"]) if parsed.get("role_name") else None,
                    "round_name": str(parsed["round_name"]) if parsed.get("round_name") else None,
                    "candidate_name": str(parsed["candidate_name"]) if parsed.get("candidate_name") else None,
                    "location": (
                        location
                        if location and parsed.get("location") and _location_similarity(location, str(parsed["location"])) < 0.4
                        else (str(parsed["location"]) if parsed.get("location") else (location or None))
                    ),
                }
        except Exception as e:
            if attempt == 0:
                logger.warning(f"Calendar Intelligence: classification attempt 1 failed: {e}, retrying")
                continue
            logger.warning(f"Calendar Intelligence: classification failed after retry: {e}")
            return None
    return None


# --- Role Resolution (Phase 2: "Which role?") ---



async def resolve_role_matches(
    analyzed: dict,
    requisitions: list[dict],
    candidates: list[dict],
    extracted_fields: Optional[dict] = None,
    requisitions_truncated: bool = False,
) -> tuple[list[dict], dict]:
    """Match an analyzed calendar event to candidate requisitions.

    Codex Round 3: when ``requisitions_truncated`` is True, the caller fetched
    only a subset of open requisitions (e.g. newest ``MAX_REQS_PER_EVENT``). In
    that case the true role for the event may have been excluded entirely, so
    auto_select must be disabled — we force manual role selection and surface
    a warning via ``match_metadata['requisitions_truncated']``.
    """
    if not requisitions:
        return [], {"match_type": "no_signal", "extraction": None, "filters": {}, "requisitions_truncated": requisitions_truncated}

    external_emails = {a["email"].lower() for a in analyzed.get("external_attendees", [])}
    email_to_reqs = email_affinity_lookup(external_emails, candidates)
    email_req_ids: set[str] = set()
    for req_ids in email_to_reqs.values():
        email_req_ids.update(req_ids)

    extracted = extracted_fields
    if not extracted:
        extracted = await llm_classify_and_extract(analyzed)

    event_location = analyzed.get("location") or ""
    if extracted:
        filtered, filter_meta = filter_requisitions_by_extracted_fields(extracted, requisitions, event_location)
    else:
        filtered = requisitions
        filter_meta = {"extraction_failed": True}
    location_no_match = bool((extracted or {}).get("location")) and filter_meta.get("location") == "no_match"

    event_description = analyzed.get("description") or ""
    scored = []
    for req in filtered:
        sc, matched_round = score_role_match(req, extracted or {}, email_req_ids, event_location, event_description)
        role_sim = 0.0
        if extracted and extracted.get("role_name"):
            role_sim = _role_similarity(extracted["role_name"], req.get("role_title") or "")
        scored.append((req, sc, matched_round, role_sim))
    scored.sort(key=lambda x: (x[1], x[3], x[0].get("created_at", "")), reverse=True)

    if len(scored) == 0:
        match_type = "no_signal"
    elif location_no_match:
        match_type = "location_mismatch"
    elif len(scored) == 1:
        match_type = "auto_select"
    elif scored[0][1] >= 0.5 and (scored[0][1] - scored[1][1]) >= 0.2:
        match_type = "auto_select"
    elif extracted and any(v for k, v in filter_meta.items() if "matched" in str(v)):
        match_type = "narrowed"
    elif email_req_ids or extracted:
        match_type = "partial_signal"
    else:
        match_type = "no_signal"

    # Codex Round 3: If the requisition list was truncated, the top of the
    # list might still look like a confident match within the visible subset
    # but the true role could be hidden beyond the cap. Downgrade auto_select
    # so the user is presented with options (or a dashboard link) instead of
    # a one-click confirmation. Signal-based strong matches (candidate email
    # affinity to one of the returned reqs) are a safe exception — if the
    # candidate is tied to a specific visible req via email, truncation does
    # not change that fact.
    candidate_email_anchor = bool(email_req_ids) and bool(scored) and str(scored[0][0]["id"]) in email_req_ids
    if requisitions_truncated and match_type == "auto_select" and not candidate_email_anchor:
        if len(scored) >= 2:
            match_type = "narrowed"
        else:
            match_type = "partial_signal"

    ranked = [s[0] for s in scored]
    filtered_ids = {str(r["id"]) for r in ranked}
    remaining = [r for r in requisitions if str(r["id"]) not in filtered_ids]
    remaining.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    ranked.extend(remaining)

    top = scored[0] if scored else (None, 0.0, None, 0.0)
    score_hint_limit = min(len(scored), MAX_NARROWED_SCORE_HINTS)
    match_metadata = {
        "match_type": match_type,
        "extraction": extracted,
        "filters": filter_meta,
        "location_no_match": location_no_match,
        "email_req_ids": list(email_req_ids),
        "top_score": top[1],
        "matched_round_id": top[2],
        "scores": {str(s[0]["id"]): s[1] for s in scored[:score_hint_limit]},
        "requisitions_truncated": requisitions_truncated,
    }

    return ranked, match_metadata


def resolve_organizer(event: dict, platform_users: dict[str, dict]) -> Optional[str]:
    raw = event.get("raw", {})
    organizer_email = raw.get("organizer", {}).get("email", "")
    if organizer_email and organizer_email.lower() in platform_users:
        return platform_users[organizer_email.lower()]["profile_id"]

    attendees = raw.get("attendees", [])
    for att in attendees:
        email = att.get("email", "").lower()
        if email in platform_users:
            return platform_users[email]["profile_id"]

    return None


async def match_candidate(email: str, requisition_id: str) -> Optional[dict]:
    if not email:
        return None
    supabase = get_supabase_admin_client()
    result = await supabase.table("candidates") \
        .select("id, name, email") \
        .eq("requisition_id", requisition_id) \
        .eq("email", email.lower()) \
        .is_("deleted_at", "null") \
        .execute_async()
    return result.data[0] if result.data else None


def resolve_candidate_name(analyzed: dict, external_email: str) -> str:
    classification = analyzed.get("detection_signals", {}).get("classification", {}) if isinstance(analyzed.get("detection_signals"), dict) else {}
    classified_candidate = str(classification.get("candidate_name") or "").strip() if isinstance(classification, dict) else ""

    title_candidate = _extract_candidate_name_from_title(
        str(analyzed.get("event_title") or ""),
        analyzed.get("internal_attendees") or [],
        external_attendees=analyzed.get("external_attendees") or [],
        candidate_email=external_email,
    )
    if title_candidate:
        return title_candidate

    if classified_candidate:
        return classified_candidate

    for att in analyzed.get("external_attendees", []):
        if att.get("email", "").lower() == external_email.lower():
            display_name = att.get("display_name", "").strip()
            if display_name:
                return display_name

    local = external_email.split("@")[0] if "@" in external_email else external_email
    parts = re.split(r'[._\-+]', local)
    return " ".join(p.capitalize() for p in parts if p)


def check_interviewer_match(
    analyzed: dict, round_data: dict
) -> str:
    default_emails = round_data.get("default_interviewer_emails") or []
    if not default_emails:
        return "unset"

    internal_emails = {a["email"].lower() for a in analyzed.get("internal_attendees", [])}
    default_set = {e.lower() for e in default_emails}

    if internal_emails & default_set:
        return "match"
    return "mismatch"


def resolve_interviewer_email(
    internal_attendees: list[dict],
    round_data: dict | None,
    recruiter_email: str,
) -> str | None:
    """Resolve the primary interviewer email from calendar event attendees.

    Smart cascade:
      P1: round default_interviewer_emails that match an internal attendee
      P2: sole internal attendee (covers recruiter screen)
      P3: non-recruiter internal attendees, sorted for determinism
      P4: fallback to recruiter email
    """
    try:
        internals = {a["email"].lower() for a in internal_attendees if isinstance(a, dict) and a.get("email")}
    except (KeyError, TypeError, AttributeError):
        return recruiter_email or None

    if not internals:
        return recruiter_email or None

    if round_data:
        defaults = round_data.get("default_interviewer_emails") or []
        matched = [e for e in defaults if e.lower() in internals]
        if matched:
            return matched[0]

    if len(internals) == 1:
        return list(internals)[0]

    recruiter_lower = (recruiter_email or "").lower()
    non_recruiter = sorted(e for e in internals if e != recruiter_lower)
    if non_recruiter:
        return non_recruiter[0]

    return recruiter_email or None


# --- Block Kit Builders (Phase 3) ---














































