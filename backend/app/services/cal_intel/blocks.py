"""Slack Block Kit builders + the detection presentation/context model.

Pure presentation layer: turns a detection dict into Slack blocks/modals. No DB,
no network. Moved verbatim out of ``calendar_intelligence_service`` (which now
re-exports these names so handler / worker / tests keep importing them from the
original path unchanged).
"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape as html_escape
from typing import Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.services.cal_intel.policy import ConfidenceTier
from app.services.cal_intel.matching import (
    _coerce_timezone_name,
    _email_local_to_name,
    _extract_candidate_from_title,
    _extract_candidate_name_from_title,
    _extract_interviewer_name_from_title,
    _format_created_date,
    _format_event_time,
)


_DEFAULT_CONTEXT_UNKNOWN = "Unknown"
_DEFAULT_CONTEXT_NOT_SET = "Not set"
_INTERACTION_STEP_LABELS = {
    "detected": "Detected",
    "role_select": "Selecting Role",
    "round_select": "Selecting Round",
    "review": "Review",
    "confirmed": "Confirmed",
    "undone": "Undone",
    "dismissed": "Dismissed",
    "not_interview": "Not Interview",
    "orphan": "Reminder Pending",
}
_STATUS_TO_INTERACTION_STEP = {
    "detected": "detected",
    "notified": "role_select",
    "awaiting_role": "role_select",
    "awaiting_round": "round_select",
    "awaiting_confirm": "review",
    "confirming": "review",
    "confirmed": "confirmed",
    "undone": "undone",
    "dismissed": "dismissed",
    "not_interview": "not_interview",
    "orphan_no_response": "orphan",
    "orphan_role": "orphan",
    "orphan_round": "orphan",
    "orphan_confirm": "orphan",
    "expired": "orphan",
}


def _add_role_url() -> str:
    settings = get_settings()
    base = (settings.APP_URL or "").strip()
    if not base:
        base = "http://localhost:3005"
    return f"{base.rstrip('/')}/dashboard"


def _interaction_step_label(step: str) -> str:
    step_key = (step or "").strip().lower()
    if not step_key:
        return _INTERACTION_STEP_LABELS["detected"]
    return _INTERACTION_STEP_LABELS.get(step_key, step_key.replace("_", " ").title())


def _status_to_interaction_step(status: str) -> str:
    status_key = (status or "").strip().lower()
    return _STATUS_TO_INTERACTION_STEP.get(status_key, "detected")


def _coalesce_text(*values: str, fallback: str = "") -> str:
    for value in values:
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return fallback


def _display_value(value: str, fallback: str = "Not available") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    lowered = text.lower()
    if lowered in {"unknown", "not set", "n/a", "na", "none", "null", "tbd"}:
        return fallback
    return text


def _format_meeting_platform(value: str) -> str:
    platform = str(value or "").strip().lower()
    if not platform:
        return "Not available"
    known = {
        "google_meet": "Google Meet",
        "zoom": "Zoom",
        "teams": "Microsoft Teams",
        "webex": "Webex",
    }
    return known.get(platform, platform.replace("_", " ").title())


def build_app_action_url(
    detection: dict | None = None,
    *,
    detection_id: str = "",
    requisition_id: str = "",
    candidate_round_id: str = "",
) -> str:
    base = _add_role_url()
    params: dict[str, str] = {}
    detection_obj = detection or {}
    did = _coalesce_text(detection_id, str(detection_obj.get("id") or ""))
    req_id = _coalesce_text(requisition_id, str(detection_obj.get("matched_requisition_id") or ""))
    cr_id = _coalesce_text(candidate_round_id, str(detection_obj.get("matched_candidate_round_id") or ""))
    if did:
        params["detection_id"] = did
    if req_id:
        params["requisition_id"] = req_id
    if cr_id:
        params["candidate_round_id"] = cr_id
    if not params:
        return base
    return f"{base}?{urlencode(params)}"


def build_interaction_context(
    detection: dict,
    *,
    role_title: str = "",
    round_name: str = "",
    candidate_name: str = "",
    candidate_email: str = "",
    interviewer_name: str = "",
    interviewer_email: str = "",
    current_step: str = "",
    app_url: str = "",
) -> dict:
    signals = detection.get("detection_signals") or {}
    if not isinstance(signals, dict):
        signals = {}
    prev = signals.get("interaction_context") or {}
    if not isinstance(prev, dict):
        prev = {}
    ui_state = signals.get("_ui_state") or {}
    if not isinstance(ui_state, dict):
        ui_state = {}
    classification = signals.get("classification") or {}
    if not isinstance(classification, dict):
        classification = {}

    title = _coalesce_text(
        str(detection.get("event_title") or ""),
        str(prev.get("event_title") or ""),
        fallback="Meeting",
    )
    tz_name = _resolve_display_timezone(detection)
    event_start_display = _format_event_time(detection.get("event_start"), tz_name)

    external = detection.get("external_attendees") or []
    if not isinstance(external, list):
        external = []
    first_external = external[0] if external and isinstance(external[0], dict) else {}
    internal = detection.get("internal_attendees") or []
    if not isinstance(internal, list):
        internal = []
    first_non_self_internal = next(
        (
            a for a in internal
            if isinstance(a, dict) and a.get("email") and not a.get("self")
        ),
        {},
    )
    first_self_internal = next(
        (
            a for a in internal
            if isinstance(a, dict) and a.get("email") and a.get("self")
        ),
        {},
    )

    title_name, title_email = _extract_candidate_from_title(title)

    candidate_email_val = _coalesce_text(
        candidate_email,
        str(first_external.get("email") or ""),
        str(title_email or ""),
        str(prev.get("candidate_email") or ""),
    ).lower()
    if not candidate_email_val:
        candidate_email_val = _DEFAULT_CONTEXT_NOT_SET

    title_candidate_name = _extract_candidate_name_from_title(
        title,
        internal,
        external_attendees=external,
        candidate_email=(candidate_email_val if candidate_email_val != _DEFAULT_CONTEXT_NOT_SET else ""),
    )

    candidate_name_val = _coalesce_text(
        candidate_name,
        str(classification.get("candidate_name") or ""),
        str(title_candidate_name or ""),
        str(first_external.get("display_name") or ""),
        str(title_name or ""),
        str(prev.get("candidate_name") or ""),
    )
    if not candidate_name_val and candidate_email_val not in {"", _DEFAULT_CONTEXT_NOT_SET}:
        candidate_name_val = _email_local_to_name(candidate_email_val)
    if not candidate_name_val:
        candidate_name_val = _DEFAULT_CONTEXT_UNKNOWN

    non_self_internal = [
        str(a.get("email") or "").strip().lower()
        for a in internal
        if isinstance(a, dict) and a.get("email") and not a.get("self")
    ]
    self_internal = [
        str(a.get("email") or "").strip().lower()
        for a in internal
        if isinstance(a, dict) and a.get("email") and a.get("self")
    ]
    interviewer_email_val = _coalesce_text(
        interviewer_email,
        str(prev.get("interviewer_email") or ""),
        non_self_internal[0] if non_self_internal else "",
        self_internal[0] if self_internal else "",
    ).lower()
    if not interviewer_email_val:
        interviewer_email_val = _DEFAULT_CONTEXT_NOT_SET

    title_interviewer_name = _extract_interviewer_name_from_title(
        title,
        internal,
        interviewer_email=(interviewer_email_val if interviewer_email_val != _DEFAULT_CONTEXT_NOT_SET else ""),
        candidate_name=title_candidate_name or candidate_name_val,
    )

    matched_interviewer = next(
        (
            a for a in internal
            if isinstance(a, dict)
            and str(a.get("email") or "").strip().lower() == interviewer_email_val
        ),
        {},
    )
    interviewer_name_val = _coalesce_text(
        interviewer_name,
        str(prev.get("interviewer_name") or ""),
        str(matched_interviewer.get("display_name") or ""),
        str(first_non_self_internal.get("display_name") or ""),
        str(first_self_internal.get("display_name") or ""),
        str(title_interviewer_name or ""),
    )
    if not interviewer_name_val and interviewer_email_val not in {"", _DEFAULT_CONTEXT_NOT_SET}:
        interviewer_name_val = _email_local_to_name(interviewer_email_val)
    if not interviewer_name_val:
        interviewer_name_val = _DEFAULT_CONTEXT_NOT_SET

    role_title_val = _coalesce_text(
        role_title,
        str(ui_state.get("role_title") or ""),
        str(prev.get("role_title") or ""),
        str(classification.get("role_name") or ""),
        fallback=_DEFAULT_CONTEXT_NOT_SET,
    )
    round_name_val = _coalesce_text(
        round_name,
        str(prev.get("round_name") or ""),
        str(classification.get("round_name") or ""),
        fallback=_DEFAULT_CONTEXT_NOT_SET,
    )

    step_key = _coalesce_text(
        current_step,
        str(ui_state.get("current_step") or ""),
        str(prev.get("current_step_key") or ""),
        _status_to_interaction_step(str(detection.get("detection_status") or "")),
        fallback="detected",
    ).lower()
    step_label = _interaction_step_label(step_key)

    app_url_val = _coalesce_text(
        app_url,
        str(prev.get("app_url") or ""),
        build_app_action_url(detection),
    )

    return {
        "event_title": title,
        "event_start_display": event_start_display,
        "candidate_name": candidate_name_val,
        "candidate_email": candidate_email_val,
        "interviewer_name": interviewer_name_val,
        "role_title": role_title_val,
        "round_name": round_name_val,
        "interviewer_email": interviewer_email_val,
        "current_step": step_label,
        "current_step_key": step_key,
        "app_url": app_url_val,
    }


def merge_interaction_context(
    signals: dict | None,
    detection: dict,
    **overrides,
) -> dict:
    next_signals = dict(signals or {})
    context_detection = dict(detection or {})
    context_detection["detection_signals"] = next_signals
    next_signals["interaction_context"] = build_interaction_context(
        context_detection,
        **overrides,
    )
    return next_signals


def build_open_in_app_button(detection: dict, label: str = "Open in OpenRecruiting") -> dict:
    context = build_interaction_context(detection)
    detection_id = str(detection.get("id", ""))
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": label},
        "action_id": "cal_intel_open_dashboard",
        "url": context.get("app_url") or build_app_action_url(detection),
        "value": json.dumps({"detection_id": detection_id}),
    }


def build_open_in_app_action_block(detection: dict, scope: str) -> dict:
    detection_id = str(detection.get("id", ""))
    return {
        "type": "actions",
        "block_id": f"cal_intel_open_app_{scope}_{detection_id[:8]}",
        "elements": [build_open_in_app_button(detection)],
    }


def _resolve_display_timezone(detection: dict) -> str:
    signals = detection.get("detection_signals") or {}
    if not isinstance(signals, dict):
        return ""
    display = _coerce_timezone_name(str(signals.get("_display_timezone") or ""))
    if display:
        try:
            ZoneInfo(display)
            return display
        except Exception:
            pass
    event_tz = _coerce_timezone_name(str(signals.get("_event_timezone") or ""))
    if event_tz:
        try:
            ZoneInfo(event_tz)
            return event_tz
        except Exception:
            pass
    return ""


def build_guidelines_html(guidelines: list[dict] | None) -> str:
    """Render guidelines into safe, consistently styled HTML."""
    if not guidelines:
        return ""

    parts: list[str] = []
    for g in guidelines:
        if not isinstance(g, dict):
            continue
        title = html_escape(str(g.get("title") or "").strip())
        desc = html_escape(str(g.get("description") or "").strip()).replace("\n", "<br>")
        if not title and not desc:
            continue
        if title:
            parts.append(f"<p style=\"margin: 0 0 6px 0;\"><strong>{title}</strong></p>")
        if desc:
            parts.append(f"<p style=\"margin: 0 0 14px 0;\">{desc}</p>")

    return "".join(parts)


def _build_context_header(
    detection: dict,
    role_title: str = "",
    *,
    round_name: str = "",
    candidate_name: str = "",
    candidate_email: str = "",
    interviewer_name: str = "",
    interviewer_email: str = "",
    step_override: str = "",
) -> dict:
    context = build_interaction_context(
        detection,
        role_title=role_title,
        round_name=round_name,
        candidate_name=candidate_name,
        candidate_email=candidate_email,
        interviewer_name=interviewer_name,
        interviewer_email=interviewer_email,
        current_step=step_override,
    )
    lines = [
        f":calendar: *Interview:* {_display_value(context.get('event_title'), fallback='Meeting')}",
        f":clock3: *Date & Time:* {_display_value(context.get('event_start_display'))}",
        f":video_camera: *Meeting Platform:* {_format_meeting_platform(detection.get('meeting_platform'))}",
        f":briefcase: *Role:* {_display_value(context.get('role_title'))}",
        f":clipboard: *Round:* {_display_value(context.get('round_name'))}",
        f":bust_in_silhouette: *Candidate Name:* {_display_value(context.get('candidate_name'))}",
        f":envelope: *Candidate Email:* {_display_value(context.get('candidate_email'))}",
        f":busts_in_silhouette: *Interviewer Name:* {_display_value(context.get('interviewer_name'))}",
        f":envelope: *Interviewer Email:* {_display_value(context.get('interviewer_email'))}",
    ]

    det_id = str(detection.get("id", ""))
    return {
        "type": "section",
        "block_id": f"cal_intel_ctx_{det_id[:8]}",
        "text": {"type": "mrkdwn", "text": "\n".join(lines)},
    }


def _append_card_footer(blocks: list[dict], detection_id: str, scope: str) -> list[dict]:
    blocks.append({
        "type": "divider",
        "block_id": f"cal_intel_card_end_{scope}_{detection_id[:8]}",
    })
    return blocks


def _role_label(req: dict) -> str:
    title = req.get("role_title", "Unknown")
    loc = req.get("role_location", "")
    if loc:
        return f"{title} ({loc})"[:75]
    return title[:75]


def _role_option_label(req: dict) -> str:
    base = _role_label(req)
    created = _format_created_date(req.get("created_at", ""))
    if created:
        return f"{base} · {created}"[:75]
    return base


def build_detection_blocks(
    detection: dict, req_matches: list[dict], match_metadata: Optional[dict] = None,
) -> list[dict]:
    confidence = detection.get("detection_confidence", 0)
    tier = ConfidenceTier.ui_tier(confidence)
    detection_id = str(detection.get("id", ""))

    header_text = ":mag: *Detected interview*"
    if tier == "HIGH":
        header_text = ":white_check_mark: *Interview detected*"
    elif tier == "LOW":
        header_text = ":mag: *Potential interview detected*"

    blocks = [
        _build_context_header(detection, step_override="role_select"),
        {
            "type": "section",
            "block_id": f"cal_intel_header_{detection_id[:8]}",
            "text": {"type": "mrkdwn", "text": header_text},
        },
    ]

    meta = match_metadata or {}
    extraction = meta.get("extraction") or {}
    context_lines = []
    if extraction.get("role_name"):
        loc = extraction.get("location") or ""
        role_text = f"*{extraction['role_name']}*"
        if loc:
            role_text += f" in *{loc}*"
        context_lines.append(f":mag: Detected: {role_text}")
    if extraction.get("round_name"):
        context_lines.append(f":clipboard: Round: *{extraction['round_name']}*")
    if meta.get("email_req_ids"):
        candidate_in = len(meta["email_req_ids"])
        context_lines.append(f":link: Candidate in {candidate_in} existing role{'s' if candidate_in > 1 else ''}")
    if meta.get("match_type") == "auto_select" and meta.get("matched_round_id"):
        candidate_email = ""
        for att in (detection.get("external_attendees") or []):
            if att.get("email"):
                candidate_email = att["email"]
                break
        if candidate_email and str(req_matches[0]["id"]) not in set(meta.get("email_req_ids", [])):
            cand_name = ""
            for att in (detection.get("external_attendees") or []):
                cand_name = att.get("display_name") or ""
                break
            context_lines.append(f":new: *{cand_name or candidate_email}* will be added to this role")
    if context_lines:
        blocks.append({
            "type": "context",
            "block_id": f"cal_intel_match_ctx_{detection_id[:8]}",
            "elements": [{"type": "mrkdwn", "text": "\n".join(context_lines)}],
        })

    # Codex Round 3: surface truncation so the recruiter does not assume
    # the suggested role is the only match when >100 open reqs exist.
    if meta.get("requisitions_truncated"):
        blocks.append({
            "type": "context",
            "block_id": f"cal_intel_trunc_warn_{detection_id[:8]}",
            "elements": [{
                "type": "mrkdwn",
                "text": (
                    ":warning: Showing newest 100 open roles only — if the right "
                    "role is not listed, pick it from the dashboard."
                ),
            }],
        })

    if meta.get("location_no_match"):
        loc = extraction.get("location") or "this location"
        blocks.append({
            "type": "section",
            "block_id": f"cal_intel_location_mismatch_{detection_id[:8]}",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":warning: No open OpenRecruiting role found for *{loc}*.\n"
                    "Add this role in OpenRecruiting or choose an existing role manually."
                ),
            },
        })
        blocks.append({
            "type": "actions",
            "block_id": f"cal_intel_location_mismatch_actions_{detection_id[:8]}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Change Role"},
                    "action_id": "cal_intel_change_role",
                    "value": f'{{"detection_id": "{detection_id}"}}',
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Add Role"},
                    "url": _add_role_url(),
                    "action_id": "cal_intel_open_dashboard",
                    "value": f'{{"detection_id": "{detection_id}"}}',
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Not an interview"},
                    "action_id": "cal_intel_not_interview",
                    "value": f'{{"detection_id": "{detection_id}"}}',
                },
            ],
        })
        blocks.append(build_open_in_app_action_block(detection, "detected"))
        return _append_card_footer(blocks, detection_id, "detected")

    match_type = meta.get("match_type", "")
    display_count = len(req_matches)
    if match_type == "auto_select" and req_matches:
        display_count = 1
    elif match_type == "narrowed" and meta.get("scores"):
        display_count = len(meta["scores"])

    if display_count == 0 or not req_matches:
        blocks.append({
            "type": "actions",
            "block_id": f"cal_intel_actions_{detection_id[:8]}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Not an interview"},
                    "action_id": "cal_intel_not_interview",
                    "value": f'{{"detection_id": "{detection_id}"}}',
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Dismiss"},
                    "action_id": "cal_intel_dismiss",
                    "value": f'{{"detection_id": "{detection_id}"}}',
                },
            ],
        })
    else:
        display_reqs = req_matches[:display_count] if display_count < len(req_matches) else req_matches
        blocks.append(build_role_selection_blocks(detection_id, display_reqs))
        blocks.append(build_role_selection_actions_block(detection_id))

    blocks.append(build_open_in_app_action_block(detection, "detected"))
    return _append_card_footer(blocks, detection_id, "detected")


def build_role_action_buttons(detection_id: str, req_matches: list[dict], single_auto: bool = False) -> dict:
    if single_auto and req_matches:
        req = req_matches[0]
        return {
            "type": "actions",
            "block_id": f"cal_intel_role_actions_{detection_id[:8]}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Confirm & Set Up"},
                    "style": "primary",
                    "action_id": "cal_intel_select_role",
                    "value": f'{{"detection_id": "{detection_id}", "requisition_id": "{req["id"]}"}}',
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Change Role"},
                    "action_id": "cal_intel_change_role",
                    "value": f'{{"detection_id": "{detection_id}"}}',
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Not an interview"},
                    "action_id": "cal_intel_not_interview",
                    "value": f'{{"detection_id": "{detection_id}"}}',
                },
            ],
        }

    elements = []
    for idx, req in enumerate(req_matches[:3]):
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": _role_label(req)},
            "action_id": f"cal_intel_select_role_{idx}",
            "value": f'{{"detection_id": "{detection_id}", "requisition_id": "{req["id"]}"}}',
        })
    elements.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "Not an interview"},
        "action_id": "cal_intel_not_interview",
        "value": f'{{"detection_id": "{detection_id}"}}',
    })
    return {
        "type": "actions",
        "block_id": f"cal_intel_role_actions_{detection_id[:8]}",
        "elements": elements,
    }


def build_role_selection_blocks(detection_id: str, requisitions: list[dict]) -> dict:
    if len(requisitions) <= 100:
        return {
            "type": "section",
            "block_id": f"cal_intel_role_select_{detection_id[:8]}",
            "text": {
                "type": "mrkdwn",
                "text": f":briefcase: *Which role is this for?* ({len(requisitions)} open roles)",
            },
            "accessory": {
                "type": "static_select",
                "placeholder": {"type": "plain_text", "text": "Select a role..."},
                "action_id": "cal_intel_select_role",
                "options": [
                    {
                        "text": {"type": "plain_text", "text": _role_option_label(req)},
                        "value": f'{{"detection_id": "{detection_id}", "requisition_id": "{req["id"]}"}}',
                    }
                    for req in requisitions[:100]
                ],
            },
        }

    return {
        "type": "section",
        "block_id": f"cal_intel_role_link_{detection_id[:8]}",
        "text": {
            "type": "mrkdwn",
            "text": (
                f":briefcase: *{len(requisitions)} open roles.* "
                "Too many to show here — please set up on the dashboard."
            ),
        },
        "accessory": {
            "type": "button",
            "text": {"type": "plain_text", "text": "Add Role"},
            "action_id": "cal_intel_open_dashboard",
            "url": _add_role_url(),
            "value": f'{{"detection_id": "{detection_id}"}}',
        },
    }


def build_role_selection_actions_block(detection_id: str) -> dict:
    return {
        "type": "actions",
        "block_id": f"cal_intel_role_select_actions_{detection_id[:8]}",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Not an interview"},
                "action_id": "cal_intel_not_interview",
                "value": f'{{"detection_id": "{detection_id}"}}',
            },
        ],
    }


def build_role_selection_step_blocks(detection: dict, requisitions: list[dict]) -> list[dict]:
    detection_id = str(detection.get("id", ""))
    blocks = [_build_context_header(detection, step_override="role_select")]
    blocks.append(build_role_selection_blocks(detection_id, requisitions))
    blocks.append(build_role_selection_actions_block(detection_id))
    blocks.append(build_open_in_app_action_block(detection, "role_step"))
    return _append_card_footer(blocks, detection_id, "role_step")


def build_no_req_blocks(detection: dict, reason: str = "no_reqs") -> list[dict]:
    det_id = str(detection.get("id", ""))
    blocks = [_build_context_header(detection, step_override="role_select")]

    if reason == "no_rounds":
        msg = ":warning: Your roles don't have interview rounds set up yet. Configure rounds in OpenRecruiting to track this interview."
    else:
        msg = ":warning: No matching role found in OpenRecruiting. Create a role to track this interview."

    blocks.append({
        "type": "section",
        "block_id": f"cal_intel_no_req_{det_id[:8]}",
        "text": {"type": "mrkdwn", "text": msg},
    })
    blocks.append({
        "type": "actions",
        "block_id": f"cal_intel_no_req_actions_{det_id[:8]}",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Add Role"},
                "url": _add_role_url(),
                "action_id": "cal_intel_open_dashboard",
                "value": f'{{"detection_id": "{det_id}"}}',
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Retry Match"},
                "action_id": "cal_intel_retry_match",
                "value": f'{{"detection_id": "{det_id}"}}',
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Not an interview"},
                "action_id": "cal_intel_not_interview",
                "value": f'{{"detection_id": "{det_id}"}}',
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Dismiss"},
                "action_id": "cal_intel_dismiss",
                "value": f'{{"detection_id": "{det_id}"}}',
            },
        ],
    })
    blocks.append(build_open_in_app_action_block(detection, "no_req"))
    return _append_card_footer(blocks, det_id, "no_req")


def build_untracked_captured_blocks(
    detection: dict,
    *,
    candidate_name: str = "",
    candidate_email: str = "",
) -> list[dict]:
    det_id = str(detection.get("id", ""))
    display_candidate_name = candidate_name.strip() or "Unknown Candidate"
    display_candidate_email = candidate_email.strip() or "unknown@untracked.local"

    blocks = [_build_context_header(detection, step_override="confirmed")]
    blocks.append({
        "type": "section",
        "block_id": f"cal_intel_untracked_captured_{det_id[:8]}",
        "text": {"type": "mrkdwn", "text": ":white_check_mark: *Interview captured*"},
    })
    blocks.append({
        "type": "section",
        "block_id": f"cal_intel_untracked_candidate_{det_id[:8]}",
        "text": {
            "type": "mrkdwn",
            "text": f"*Candidate:* {display_candidate_name} ({display_candidate_email})",
        },
    })
    blocks.append({
        "type": "section",
        "block_id": f"cal_intel_untracked_help_{det_id[:8]}",
        "text": {
            "type": "mrkdwn",
            "text": (
                "This interview will be recorded. You can import it into a role later "
                "from the requisition page."
            ),
        },
    })
    blocks.append({
        "type": "actions",
        "block_id": f"cal_intel_untracked_actions_{det_id[:8]}",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Dismiss"},
                "action_id": "cal_intel_dismiss",
                "value": f'{{"detection_id": "{det_id}"}}',
            },
        ],
    })
    blocks.append(build_open_in_app_action_block(detection, "untracked_capture"))
    return _append_card_footer(blocks, det_id, "untracked_capture")


def build_round_selection_blocks(
    detection_id: str, rounds: list[dict], interviewer_status: str = "unset",
    detection: dict = None, role_title: str = "",
    show_back_to_role: bool = False,
    back_action_id: str = "cal_intel_back_role",
    back_button_text: str = "Back to Roles",
) -> list[dict]:
    blocks = []

    if detection:
        blocks.append(_build_context_header(detection, role_title, step_override="round_select"))

    if interviewer_status == "match":
        blocks.append({
            "type": "context",
            "block_id": f"cal_intel_interviewer_match_{detection_id[:8]}",
            "elements": [{"type": "mrkdwn", "text": ":white_check_mark: Interviewer matches this round"}],
        })
    elif interviewer_status == "mismatch":
        blocks.append({
            "type": "context",
            "block_id": f"cal_intel_interviewer_mismatch_{detection_id[:8]}",
            "elements": [{"type": "mrkdwn", "text": ":warning: Interviewer doesn't match assigned round interviewer"}],
        })

    if len(rounds) == 1:
        r = rounds[0]
        blocks.append({
            "type": "section",
            "block_id": f"cal_intel_round_auto_{detection_id[:8]}",
            "text": {
                "type": "mrkdwn",
                "text": f":arrow_right: *Round:* {r.get('name', 'Round')} ({r.get('duration_minutes', 45)} min)",
            },
        })
        elements = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Use This Round"},
                "style": "primary",
                "action_id": "cal_intel_select_round",
                "value": f'{{"detection_id": "{detection_id}", "round_id": "{r["id"]}"}}',
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Not an interview"},
                "action_id": "cal_intel_not_interview",
                "value": f'{{"detection_id": "{detection_id}"}}',
            },
        ]
        if show_back_to_role:
            elements.insert(1, {
                "type": "button",
                "text": {"type": "plain_text", "text": back_button_text},
                "action_id": back_action_id,
                "value": f'{{"detection_id": "{detection_id}"}}',
            })
        blocks.append({
            "type": "actions",
            "block_id": f"cal_intel_round_actions_{detection_id[:8]}",
            "elements": elements,
        })
    else:
        if len(rounds) <= 5:
            elements = []
            for idx, r in enumerate(rounds):
                label = f"{r.get('name', 'Round')} ({r.get('duration_minutes', 45)}m)"
                elements.append({
                    "type": "button",
                    "text": {"type": "plain_text", "text": label[:75]},
                    "action_id": f"cal_intel_select_round_{idx}",
                    "value": f'{{"detection_id": "{detection_id}", "round_id": "{r["id"]}"}}',
                })
            round_button_count = len(elements)
            blocks.append({
                "type": "section",
                "block_id": f"cal_intel_round_select_{detection_id[:8]}",
                "text": {"type": "mrkdwn", "text": ":clipboard: *Which round?*"},
            })
            if show_back_to_role and round_button_count < 5:
                elements.append({
                    "type": "button",
                    "text": {"type": "plain_text", "text": back_button_text},
                    "action_id": back_action_id,
                    "value": f'{{"detection_id": "{detection_id}"}}',
                })
            blocks.append({
                "type": "actions",
                "block_id": f"cal_intel_round_actions_{detection_id[:8]}",
                "elements": elements,
            })
            if show_back_to_role and round_button_count >= 5:
                blocks.append({
                    "type": "actions",
                    "block_id": f"cal_intel_round_back_{detection_id[:8]}",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": back_button_text},
                            "action_id": back_action_id,
                            "value": f'{{"detection_id": "{detection_id}"}}',
                        },
                    ],
                })
        else:
            blocks.append({
                "type": "section",
                "block_id": f"cal_intel_round_select_{detection_id[:8]}",
                "text": {"type": "mrkdwn", "text": ":clipboard: *Which round?*"},
                "accessory": {
                    "type": "static_select",
                    "placeholder": {"type": "plain_text", "text": "Select a round..."},
                    "action_id": "cal_intel_select_round",
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": f"{r.get('name', 'Round')} ({r.get('duration_minutes', 45)}m)"[:75]},
                            "value": f'{{"detection_id": "{detection_id}", "round_id": "{r["id"]}"}}',
                        }
                        for r in rounds
                    ],
                },
            })
            if show_back_to_role:
                blocks.append({
                    "type": "actions",
                    "block_id": f"cal_intel_round_back_{detection_id[:8]}",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": back_button_text},
                            "action_id": back_action_id,
                            "value": f'{{"detection_id": "{detection_id}"}}',
                        },
                    ],
                })

    if detection:
        blocks.append(build_open_in_app_action_block(detection, "round_step"))
    return _append_card_footer(blocks, detection_id, "round_step")


def build_review_blocks(
    detection: dict,
    role_title: str,
    round_data: dict,
    show_back_to_round: bool = True,
) -> list[dict]:
    detection_id = str(detection.get("id", ""))
    round_name = round_data.get("name", "Round")
    back_action_id = "cal_intel_back_round" if show_back_to_round else "cal_intel_back_role"
    back_text = "Back to Rounds" if show_back_to_round else "Back to Roles"

    blocks = [_build_context_header(
        detection,
        role_title,
        round_name=round_name,
        step_override="review",
    )]
    blocks.append({
        "type": "section",
        "block_id": f"cal_intel_review_{detection_id[:8]}",
        "text": {
            "type": "mrkdwn",
            "text": ":memo: *Review setup before confirming*",
        },
    })
    blocks.append({
        "type": "actions",
        "block_id": f"cal_intel_review_actions_{detection_id[:8]}",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Confirm & Set Up"},
                "style": "primary",
                "action_id": "cal_intel_confirm_setup",
                "value": f'{{"detection_id": "{detection_id}", "round_id": "{round_data["id"]}"}}',
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": back_text},
                "action_id": back_action_id,
                "value": f'{{"detection_id": "{detection_id}"}}',
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Change Role"},
                "action_id": "cal_intel_change_role",
                "value": f'{{"detection_id": "{detection_id}"}}',
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Not an interview"},
                "action_id": "cal_intel_not_interview",
                "value": f'{{"detection_id": "{detection_id}"}}',
            },
        ],
    })
    blocks.append(build_open_in_app_action_block(detection, "review"))
    return _append_card_footer(blocks, detection_id, "review")


def build_confirmation_blocks(
    detection: dict,
    candidate_name: str,
    round_name: str,
    role_title: str = "",
    candidate_email: str = "",
    interviewer_name: str = "",
    interviewer_email: str = "",
    include_actions: bool = True,
    include_send_prep: bool = True,
    include_undo: bool = True,
    extra_status_lines: Optional[list[str]] = None,
) -> list[dict]:
    detection_id = str(detection.get("id", ""))
    detail_lines = [":white_check_mark: *Interview scheduled*"]
    blocks = [_build_context_header(
        detection,
        role_title,
        round_name=round_name,
        candidate_name=candidate_name,
        candidate_email=candidate_email,
        interviewer_name=interviewer_name,
        interviewer_email=interviewer_email,
        step_override="confirmed",
    )]
    blocks.append({
        "type": "section",
        "block_id": f"cal_intel_confirmed_{detection_id[:8]}",
        "text": {
            "type": "mrkdwn",
            "text": "\n".join(detail_lines),
        },
    })
    if extra_status_lines:
        blocks.append({
            "type": "section",
            "block_id": f"cal_intel_confirmed_status_{detection_id[:8]}",
            "text": {
                "type": "mrkdwn",
                "text": "\n".join(extra_status_lines),
            },
        })

    if not include_actions:
        blocks.append(build_open_in_app_action_block(detection, "confirmed"))
        return _append_card_footer(blocks, detection_id, "confirmed")

    elements = []
    if include_send_prep:
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Send Prep to Interviewer"},
            "action_id": "cal_intel_send_prep",
            "value": f'{{"detection_id": "{detection_id}"}}',
        })
    if include_undo:
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Undo"},
            "action_id": "cal_intel_undo",
            "value": f'{{"detection_id": "{detection_id}"}}',
            "style": "danger",
        })

    if not elements:
        blocks.append(build_open_in_app_action_block(detection, "confirmed"))
        return _append_card_footer(blocks, detection_id, "confirmed")

    blocks.append({
        "type": "actions",
        "block_id": f"cal_intel_post_actions_{detection_id[:8]}",
        "elements": elements,
    })
    blocks.append(build_open_in_app_action_block(detection, "confirmed"))
    return _append_card_footer(blocks, detection_id, "confirmed")


def build_reminder_blocks(detection: dict, reminder_num: int) -> list[dict]:
    detection_id = str(detection.get("id", ""))
    if reminder_num == 1:
        text = ":bell: *Reminder:* Pending interview setup."
    elif reminder_num == 2:
        text = ":bell: *Reminder:* Interview tomorrow — please confirm setup."
    else:
        text = ":rotating_light: *Last chance:* Interview in ~2 hours — complete setup now."

    context = build_interaction_context(detection, current_step="orphan")
    reminder_context_lines = [
        f":clock3: *Interview Time:* {_display_value(context.get('event_start_display'))}",
        f":briefcase: *Role:* {_display_value(context.get('role_title'))}",
        f":clipboard: *Round:* {_display_value(context.get('round_name'))}",
        (
            f":bust_in_silhouette: *Candidate:* "
            f"{_display_value(context.get('candidate_name'))} "
            f"({_display_value(context.get('candidate_email'))})"
        ),
        (
            f":busts_in_silhouette: *Interviewer:* "
            f"{_display_value(context.get('interviewer_name'))} "
            f"({_display_value(context.get('interviewer_email'))})"
        ),
    ]
    meeting_url = str(detection.get("meeting_url") or "").strip()
    if meeting_url:
        reminder_context_lines.append(f":link: *Meeting Link:* <{meeting_url}|Open meeting>")

    blocks = [
        _build_context_header(detection, step_override="orphan"),
        {
            "type": "section",
            "block_id": f"cal_intel_reminder_{detection_id[:8]}",
            "text": {"type": "mrkdwn", "text": text},
        },
        {
            "type": "section",
            "block_id": f"cal_intel_reminder_context_{detection_id[:8]}",
            "text": {"type": "mrkdwn", "text": "\n".join(reminder_context_lines)},
        },
        {
            "type": "actions",
            "block_id": f"cal_intel_reminder_actions_{detection_id[:8]}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Resume Setup"},
                    "style": "primary",
                    "action_id": "cal_intel_select_role",
                    "value": f'{{"detection_id": "{detection_id}"}}',
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Dismiss"},
                    "action_id": "cal_intel_dismiss",
                    "value": f'{{"detection_id": "{detection_id}"}}',
                },
            ],
        },
        build_open_in_app_action_block(detection, "reminder"),
    ]
    return _append_card_footer(blocks, detection_id, "reminder")


def build_reschedule_blocks(detection: dict, old_time: datetime, new_time: datetime) -> list[dict]:
    detection_id = str(detection.get("id", ""))
    title = detection.get("event_title") or "Meeting"
    tz_name = _resolve_display_timezone(detection)
    old_str = _format_event_time(old_time, tz_name)
    new_str = _format_event_time(new_time, tz_name)

    blocks = [
        _build_context_header(detection, step_override="confirmed"),
        {
            "type": "section",
            "block_id": f"cal_intel_reschedule_{detection_id[:8]}",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":arrows_counterclockwise: *Interview rescheduled*\n"
                    f"{title}\n"
                    f"~{old_str}~ → *{new_str}*"
                ),
            },
        },
        {
            "type": "actions",
            "block_id": f"cal_intel_reschedule_actions_{detection_id[:8]}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Update in OpenRecruiting"},
                    "style": "primary",
                    "action_id": "cal_intel_reschedule_update",
                    "value": f'{{"detection_id": "{detection_id}", "new_start": "{new_time.isoformat()}"}}',
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Keep Current Setup"},
                    "action_id": "cal_intel_reschedule_ack",
                    "value": f'{{"detection_id": "{detection_id}"}}',
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Undo"},
                    "action_id": "cal_intel_undo",
                    "value": f'{{"detection_id": "{detection_id}"}}',
                    "style": "danger",
                },
            ],
        },
        build_open_in_app_action_block(detection, "reschedule"),
    ]
    return _append_card_footer(blocks, detection_id, "reschedule")


def build_attendee_change_blocks(
    detection: dict,
    old_internal_emails: set[str],
    new_internal_emails: set[str],
    old_external_emails: set[str],
    new_external_emails: set[str],
) -> list[dict]:
    detection_id = str(detection.get("id", ""))
    title = detection.get("event_title") or "Meeting"
    blocks: list[dict] = []

    internal_added = new_internal_emails - old_internal_emails
    internal_removed = old_internal_emails - new_internal_emails
    external_added = new_external_emails - old_external_emails
    external_removed = old_external_emails - new_external_emails

    lines = []
    if internal_removed or internal_added:
        lines.append(":busts_in_silhouette: *Interviewer changed*")
        lines.append(title)
        if internal_removed:
            lines.append(f"Removed: {', '.join(sorted(internal_removed))}")
        if internal_added:
            lines.append(f"Added: {', '.join(sorted(internal_added))}")

    if external_removed or external_added:
        lines.append(":warning: *Candidate attendee changed*")
        if not (internal_removed or internal_added):
            lines.append(title)
        if external_removed:
            lines.append(f"Removed: {', '.join(sorted(external_removed))}")
        if external_added:
            lines.append(f"Added: {', '.join(sorted(external_added))}")
        lines.append("_The linked candidate in OpenRecruiting was not changed. Please review in your dashboard if needed._")

    if lines:
        blocks.append({
            "type": "section",
            "block_id": f"cal_intel_attendee_{detection_id[:8]}",
            "text": {"type": "mrkdwn", "text": "\n".join(lines)},
        })

    elements = []
    if internal_removed or internal_added:
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Send prep to new interviewer"},
            "style": "primary",
            "action_id": "cal_intel_send_prep",
            "value": f'{{"detection_id": "{detection_id}"}}',
        })
    elements.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "Got it"},
        "action_id": "cal_intel_ack_attendee_change",
        "value": f'{{"detection_id": "{detection_id}"}}',
    })
    elements.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "Undo"},
        "action_id": "cal_intel_undo",
        "value": f'{{"detection_id": "{detection_id}"}}',
        "style": "danger",
    })
    elements.append(build_open_in_app_button(detection))
    blocks.append({
        "type": "actions",
        "block_id": f"cal_intel_attendee_actions_{detection_id[:8]}",
        "elements": elements,
    })
    return blocks


def build_error_blocks(message: str) -> list[dict]:
    return [
        {
            "type": "section",
            "block_id": "cal_intel_error",
            "text": {"type": "mrkdwn", "text": f":x: {message}"},
        },
    ]


def build_role_modal(detection_id: str, requisitions: list[dict]) -> dict:
    options = []
    for req in requisitions[:100]:
        options.append({
            "text": {"type": "plain_text", "text": _role_option_label(req)},
            "value": str(req["id"]),
        })

    return {
        "type": "modal",
        "callback_id": f"cal_intel_modal_{detection_id}",
        "title": {"type": "plain_text", "text": "Select Role"},
        "submit": {"type": "plain_text", "text": "Select"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "role_select_block",
                "element": {
                    "type": "static_select",
                    "action_id": "role_select_action",
                    "placeholder": {"type": "plain_text", "text": "Choose a role..."},
                    "options": options,
                },
                "label": {"type": "plain_text", "text": "Which role is this interview for?"},
            }
        ],
    }
