import json
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional
from app.config import get_settings
from app.logging_config import get_logger
from app.services.supabase import get_supabase_admin_client
from app.services.slack_service import get_slack_service
from app.services.cal_intel.policy import (
    ATTACHABLE_BOT_STATUSES,
    BOT_SPINUP_STATUSES,
    CONFIRMABLE_STATUSES,
    CONFIRM_LOCKED_STATUSES,
    SELECT_LOCKED_STATUSES,
    TERMINAL_STATUSES,
)
from app.services.calendar_intelligence_service import (
    transition_detection_status,
    build_detection_blocks,
    build_no_req_blocks,
    build_untracked_captured_blocks,
    build_confirmation_blocks,
    build_round_selection_blocks,
    build_error_blocks,
    build_role_modal,
    build_role_selection_step_blocks,
    build_review_blocks,
    _build_context_header,
    build_open_in_app_action_block,
    check_interviewer_match,
    build_guidelines_html,
    format_event_time_for_email,
    merge_interaction_context,
)
from app.services.untracked_capture_service import (
    capture_untracked_interview,
    get_auto_join_untracked_preference,
    is_untracked_capture_enabled,
)
from app.services.untracked_import_service import (
    EXISTING_ROUND_CONFLICT_CODE,
    UntrackedImportError,
    UntrackedImportService,
)

logger = get_logger(__name__)


class CalendarIntelligenceError(Exception):
    pass

class DetectionExpiredError(CalendarIntelligenceError):
    pass

class DetectionAlreadyProcessedError(CalendarIntelligenceError):
    pass

class RequisitionDeletedError(CalendarIntelligenceError):
    pass

class RoundDeletedError(CalendarIntelligenceError):
    pass

class BotDeploymentError(CalendarIntelligenceError):
    pass

class UndoExpiredError(CalendarIntelligenceError):
    pass


# Codex Round 4: cap how many role candidates we persist into
# detection_signals._ui_state. Without a cap, a tenant with thousands of open
# requisitions could blow the detection_signals JSON past PostgreSQL row /
# payload limits, causing update failures that brick the Change Role / back
# navigation recovery paths. The cached list is a display/ranking hint only —
# the authoritative list is always re-fetched live — so capping at 100 keeps
# Slack rendering intact (modals/dropdowns already cap at 100) without hiding
# any roles from recovery flows.
MAX_PERSISTED_ROLE_CANDIDATES = 100


def _extract_value_from_action(action: dict) -> dict:
    """Extract value dict from button or static_select action payload."""
    value_str = action.get("value", "")
    if value_str:
        try:
            return json.loads(value_str)
        except json.JSONDecodeError:
            pass

    selected = action.get("selected_option", {})
    if selected:
        sel_val = selected.get("value", "")
        if sel_val:
            try:
                return json.loads(sel_val)
            except json.JSONDecodeError:
                return {"requisition_id": sel_val}

    return {}


def _error_message_block(message: str, detection_id: str, scope: str) -> dict:
    return {
        "type": "section",
        "block_id": f"cal_intel_error_{scope}_{detection_id[:8] if detection_id else 'generic'}",
        "text": {"type": "mrkdwn", "text": f":x: {message}"},
    }


def _extract_existing_round_conflict_detail(detail) -> Optional[dict]:
    if not isinstance(detail, dict):
        return None
    if str(detail.get("code") or "") != EXISTING_ROUND_CONFLICT_CODE:
        return None
    conflict = detail.get("conflict")
    if not isinstance(conflict, dict):
        return None
    return {
        "message": str(detail.get("message") or "This candidate already has this round."),
        "conflict": conflict,
    }


def _build_untracked_import_conflict_blocks(
    detection: dict,
    *,
    round_id: str,
    role_title: str,
    round_data: dict,
    detail: dict,
) -> list[dict]:
    detection_id = str(detection.get("id") or "")
    conflict = detail.get("conflict") if isinstance(detail, dict) else {}
    if not isinstance(conflict, dict):
        conflict = {}

    existing_status = str(conflict.get("existing_status") or "unknown")
    has_recording = bool(conflict.get("has_recording"))
    has_transcript = bool(conflict.get("has_transcript"))
    completed_at = str(conflict.get("completed_at") or "")
    summary_bits = [f"*Existing status:* `{existing_status}`"]
    if completed_at:
        summary_bits.append(f"*Completed at:* `{completed_at}`")
    summary_bits.append(
        f"*Artifacts:* {'recording' if has_recording else 'no recording'} / "
        f"{'transcript' if has_transcript else 'no transcript'}"
    )

    role_text = f" for *{role_title}*" if role_title else ""
    round_name = str(round_data.get("name") or "Selected round")
    warning_text = (
        f":warning: {str(detail.get('message') or 'This candidate already has this round.')}\n"
        f"Round: *{round_name}*{role_text}\n"
        + "\n".join(summary_bits)
    )

    blocks: list[dict] = [_build_context_header(detection)]
    blocks.append({
        "type": "section",
        "block_id": f"cal_intel_import_conflict_{detection_id[:8]}",
        "text": {"type": "mrkdwn", "text": warning_text},
    })
    blocks.append({
        "type": "actions",
        "block_id": f"cal_intel_import_conflict_actions_{detection_id[:8]}",
        "elements": [
            {
                "type": "button",
                "style": "primary",
                "text": {"type": "plain_text", "text": "Override and continue"},
                "action_id": "cal_intel_override_untracked_import",
                "value": json.dumps({"detection_id": detection_id, "round_id": round_id}),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Back to Rounds"},
                "action_id": "cal_intel_back_round",
                "value": json.dumps({"detection_id": detection_id}),
            },
        ],
    })
    blocks.append(build_open_in_app_action_block(detection, "action"))
    return blocks


def _back_action_for_ui_step(detection_id: str, ui_step: str) -> Optional[dict]:
    step = str(ui_step or "").strip().lower()
    if step == "review":
        return {
            "type": "button",
            "text": {"type": "plain_text", "text": "Back to Rounds"},
            "action_id": "cal_intel_back_round",
            "value": json.dumps({"detection_id": detection_id}),
        }
    if step == "round_select":
        return {
            "type": "button",
            "text": {"type": "plain_text", "text": "Back to Roles"},
            "action_id": "cal_intel_back_role",
            "value": json.dumps({"detection_id": detection_id}),
        }
    if step == "role_select":
        return {
            "type": "button",
            "text": {"type": "plain_text", "text": "Back"},
            "action_id": "cal_intel_back_detected",
            "value": json.dumps({"detection_id": detection_id}),
        }
    return None


def _normalize_attendee_email(value: str) -> str:
    return str(value or "").strip().lower()


def _candidate_options_from_detection(detection: dict) -> list[dict]:
    options: list[dict] = []
    seen: set[str] = set()
    for attendee in (detection.get("external_attendees") or []):
        if not isinstance(attendee, dict):
            continue
        email = _normalize_attendee_email(attendee.get("email"))
        if not email or "@" not in email or email in seen:
            continue
        seen.add(email)
        options.append({
            "email": email,
            "display_name": str(attendee.get("display_name") or "").strip(),
        })
    return options


def _selected_candidate_email(ui_state: dict, candidate_options: list[dict]) -> str:
    selected = _normalize_attendee_email((ui_state or {}).get("selected_candidate_email"))
    if not selected:
        return ""
    valid = {opt["email"] for opt in (candidate_options or [])}
    return selected if selected in valid else ""


def _sync_selected_candidate_email(ui_state: dict, detection: dict) -> str:
    options = _candidate_options_from_detection(detection)
    selected = _selected_candidate_email(ui_state, options)
    if len(options) == 1:
        selected = options[0]["email"]
    ui_state["selected_candidate_email"] = selected
    return selected


def _candidate_option_label(display_name: str, email: str) -> str:
    label = f"{display_name} ({email})" if display_name else email
    return label[:75]


def _add_candidate_selector_to_review_blocks(
    blocks: list[dict],
    detection_id: str,
    candidate_options: list[dict],
    *,
    selected_candidate_email: str = "",
    validation_error: str = "",
) -> list[dict]:
    if len(candidate_options) <= 1:
        return blocks

    selected = _normalize_attendee_email(selected_candidate_email)
    options_payload: list[dict] = []
    selected_option: Optional[dict] = None
    for option in candidate_options[:100]:
        payload = {
            "text": {
                "type": "plain_text",
                "text": _candidate_option_label(option.get("display_name", ""), option["email"]),
            },
            "value": json.dumps({
                "detection_id": detection_id,
                "candidate_email": option["email"],
            }),
        }
        options_payload.append(payload)
        if option["email"] == selected:
            selected_option = payload

    accessory = {
        "type": "static_select",
        "placeholder": {"type": "plain_text", "text": "Select candidate..."},
        "action_id": "cal_intel_select_candidate",
        "options": options_payload,
    }
    if selected_option:
        accessory["initial_option"] = selected_option

    info_blocks: list[dict] = [
        {
            "type": "section",
            "block_id": f"cal_intel_candidate_hint_{detection_id[:8]}",
            "text": {
                "type": "mrkdwn",
                "text": ":bust_in_silhouette: Multiple external attendees found. Select who the candidate is.",
            },
        },
        {
            "type": "section",
            "block_id": f"cal_intel_candidate_select_{detection_id[:8]}",
            "text": {"type": "mrkdwn", "text": "*Who is the candidate?*"},
            "accessory": accessory,
        },
    ]
    if validation_error:
        info_blocks.append({
            "type": "section",
            "block_id": f"cal_intel_candidate_error_{detection_id[:8]}",
            "text": {"type": "mrkdwn", "text": f":warning: {validation_error}"},
        })

    insert_at = next(
        (
            idx
            for idx, block in enumerate(blocks)
            if str(block.get("block_id") or "").startswith("cal_intel_review_actions_")
        ),
        len(blocks),
    )
    return [*blocks[:insert_at], *info_blocks, *blocks[insert_at:]]


def _build_review_blocks_with_candidate_disambiguation(
    detection: dict,
    role_title: str,
    round_data: dict,
    *,
    show_back_to_round: bool,
    ui_state: dict,
    validation_error: str = "",
) -> list[dict]:
    blocks = build_review_blocks(
        detection=detection,
        role_title=role_title,
        round_data=round_data,
        show_back_to_round=show_back_to_round,
    )
    options = _candidate_options_from_detection(detection)
    selected = _selected_candidate_email(ui_state, options)
    return _add_candidate_selector_to_review_blocks(
        blocks,
        str(detection.get("id") or ""),
        options,
        selected_candidate_email=selected,
        validation_error=validation_error,
    )


async def _build_action_error_blocks(
    detection_id: str,
    message: str,
    *,
    scope: str,
    include_retry: bool = True,
    include_back: bool = True,
    include_open: bool = True,
) -> list[dict]:
    safe_message = str(message or "").strip() or "Could not process this action."
    if not detection_id:
        return build_error_blocks(safe_message)

    try:
        detection = await _get_detection(detection_id)
    except Exception:
        return build_error_blocks(safe_message)

    blocks: list[dict] = [_build_context_header(detection)]
    blocks.append(_error_message_block(safe_message, detection_id, scope))

    signals = detection.get("detection_signals") or {}
    if not isinstance(signals, dict):
        signals = {}
    ui_state = signals.get("_ui_state") or {}
    if not isinstance(ui_state, dict):
        ui_state = {}
    ui_step = str(ui_state.get("current_step") or "")

    elements: list[dict] = []
    if include_back:
        back_action = _back_action_for_ui_step(detection_id, ui_step)
        if back_action:
            elements.append(back_action)
    if include_retry:
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Retry role matching"},
            "action_id": "cal_intel_retry_match",
            "value": json.dumps({"detection_id": detection_id}),
        })

    if elements:
        blocks.append({
            "type": "actions",
            "block_id": f"cal_intel_error_actions_{scope}_{detection_id[:8]}",
            "elements": elements[:5],
        })

    if include_open:
        blocks.append(build_open_in_app_action_block(detection, scope))

    return blocks


async def handle_cal_intel_action(action_id: str, payload: dict):
    settings = get_settings()
    if not settings.CALENDAR_INTELLIGENCE_ENABLED:
        await _update_slack_message(payload, build_error_blocks("Calendar Intelligence is temporarily disabled."))
        return

    action = payload.get("actions", [{}])[0]
    value = _extract_value_from_action(action)

    detection_id = value.get("detection_id")
    if not detection_id:
        return

    user_data = payload.get("user", {})
    actor_slack_id = user_data.get("id") if isinstance(user_data, dict) else user_data
    team_data = payload.get("team", {})
    actor_team_id = team_data.get("id") if isinstance(team_data, dict) else team_data
    if actor_slack_id:
        supabase = get_supabase_admin_client()
        detection_row = await supabase.table("calendar_event_detections") \
            .select("profile_id") \
            .eq("id", detection_id) \
            .execute_async()
        if detection_row.data:
            owner_profile_id = detection_row.data[0]["profile_id"]
            actor_query = supabase.table("slack_connections") \
                .select("profile_id") \
                .eq("slack_user_id", actor_slack_id) \
                .eq("is_active", True)
            if actor_team_id:
                actor_query = actor_query.eq("slack_team_id", actor_team_id)
            actor_conn = await actor_query.execute_async()
            actor_profile_id = actor_conn.data[0]["profile_id"] if actor_conn.data else None
            if not actor_profile_id or str(actor_profile_id) != str(owner_profile_id):
                logger.warning(f"Calendar Intelligence: unauthorized action by {actor_slack_id} on detection {detection_id}")
                await _update_slack_message(payload, build_error_blocks("You don't have permission for this action."))
                return

    try:
        if action_id == "cal_intel_change_role":
            await _select_role(detection_id, None, payload)
        elif action_id.startswith("cal_intel_select_role"):
            requisition_id = value.get("requisition_id")
            await _select_role(detection_id, requisition_id, payload)
        elif action_id.startswith("cal_intel_select_round"):
            round_id = value.get("round_id")
            await _select_round(detection_id, round_id, payload)
        elif action_id == "cal_intel_select_candidate":
            candidate_email = value.get("candidate_email")
            await _select_candidate(detection_id, candidate_email, payload)
        elif action_id in ("cal_intel_confirm", "cal_intel_confirm_setup"):
            round_id = value.get("round_id")
            await _confirm(detection_id, round_id, payload)
        elif action_id == "cal_intel_override_untracked_import":
            round_id = value.get("round_id")
            await _confirm(detection_id, round_id, payload, force_import_override=True)
        elif action_id == "cal_intel_back_role":
            await _back_to_role(detection_id, payload)
        elif action_id == "cal_intel_back_detected":
            await _back_to_detected(detection_id, payload)
        elif action_id == "cal_intel_back_round":
            await _back_to_round(detection_id, payload)
        elif action_id == "cal_intel_dismiss":
            await _dismiss(detection_id, payload)
        elif action_id == "cal_intel_not_interview":
            await _not_interview(detection_id, payload)
        elif action_id == "cal_intel_undo":
            await _undo(detection_id, payload)
        elif action_id == "cal_intel_send_prep":
            await _send_prep(detection_id, payload)
        elif action_id == "cal_intel_retry_match":
            await _select_role(detection_id, None, payload)
        elif action_id == "cal_intel_ack_attendee_change":
            detection = await _get_detection(detection_id)
            supabase = get_supabase_admin_client()
            blocks = await _build_confirmed_summary_blocks(
                detection,
                supabase,
                [":white_check_mark: Attendee change acknowledged."],
                include_send_prep=False,
            )
            await _update_slack_message(payload, blocks)
        elif action_id == "cal_intel_open_dashboard":
            pass
        elif action_id == "cal_intel_reschedule_update":
            new_start = value.get("new_start")
            await _handle_reschedule_update(detection_id, new_start, payload)
        elif action_id == "cal_intel_reschedule_ack":
            detection = await _get_detection(detection_id)
            if detection["detection_status"] != "confirmed":
                raise DetectionAlreadyProcessedError()
            supabase = get_supabase_admin_client()
            blocks = await _build_confirmed_summary_blocks(
                detection,
                supabase,
                [":white_check_mark: Reschedule notice acknowledged. OpenRecruiting schedule unchanged."],
                include_send_prep=False,
            )
            await _update_slack_message(payload, blocks)
        else:
            logger.warning(f"Calendar Intelligence: unknown action_id={action_id}")
    except DetectionAlreadyProcessedError:
        pass
    except DetectionExpiredError:
        await _update_slack_message(
            payload,
            await _build_action_error_blocks(
                detection_id,
                "This notification has expired.",
                scope="expired",
                include_retry=False,
                include_back=False,
            ),
        )
    except RequisitionDeletedError:
        await _update_slack_message(
            payload,
            await _build_action_error_blocks(
                detection_id,
                "This role was deleted.",
                scope="req_deleted",
                include_retry=True,
                include_back=True,
            ),
        )
    except RoundDeletedError:
        await _update_slack_message(
            payload,
            await _build_action_error_blocks(
                detection_id,
                "This round no longer exists.",
                scope="round_deleted",
                include_retry=True,
                include_back=True,
            ),
        )
    except UndoExpiredError:
        await _update_slack_message(
            payload,
            await _build_action_error_blocks(
                detection_id,
                "Undo window expired. This interview is still confirmed in OpenRecruiting.",
                scope="undo_expired",
                include_retry=False,
                include_back=False,
            ),
        )
    except BotDeploymentError as e:
        await _update_slack_message(
            payload,
            await _build_action_error_blocks(
                detection_id,
                f"Bot failed: {e}",
                scope="bot_failed",
                include_retry=True,
                include_back=True,
            ),
        )
    except CalendarIntelligenceError as e:
        message = str(e).strip() or "Could not process this action."
        await _update_slack_message(
            payload,
            await _build_action_error_blocks(
                detection_id,
                message,
                scope="action",
                include_retry=True,
                include_back=True,
            ),
        )
    except Exception as e:
        logger.error(f"Calendar Intelligence action failed: {e}", exc_info=True)
        await _update_slack_message(
            payload,
            await _build_action_error_blocks(
                detection_id,
                "Something went wrong.",
                scope="unknown",
                include_retry=True,
                include_back=True,
            ),
        )


async def handle_cal_intel_modal_submit(payload: dict):
    settings = get_settings()
    if not settings.CALENDAR_INTELLIGENCE_ENABLED:
        return

    view = payload.get("view", {})
    callback_id = view.get("callback_id", "")
    detection_id = callback_id.replace("cal_intel_modal_", "")

    values = view.get("state", {}).get("values", {})
    selected = values.get("role_select_block", {}).get("role_select_action", {}).get("selected_option", {})
    requisition_id = selected.get("value")

    if detection_id and requisition_id:
        supabase = get_supabase_admin_client()
        det = await supabase.table("calendar_event_detections") \
            .select("slack_channel_id, slack_message_ts, profile_id") \
            .eq("id", detection_id) \
            .execute_async()
        if det.data:
            row = det.data[0]
            actor_user = payload.get("user", {})
            actor_slack_id = actor_user.get("id") if isinstance(actor_user, dict) else None
            actor_team_data = actor_user.get("team_id") or (payload.get("team", {}).get("id") if isinstance(payload.get("team"), dict) else payload.get("team"))
            if actor_slack_id:
                actor_query = supabase.table("slack_connections") \
                    .select("profile_id") \
                    .eq("slack_user_id", actor_slack_id) \
                    .eq("is_active", True)
                if actor_team_data:
                    actor_query = actor_query.eq("slack_team_id", actor_team_data)
                actor_conn = await actor_query.execute_async()
                actor_profile_id = actor_conn.data[0]["profile_id"] if actor_conn.data else None
                if not actor_profile_id or str(actor_profile_id) != str(row["profile_id"]):
                    logger.warning(f"Calendar Intelligence: unauthorized modal submit by {actor_slack_id} on detection {detection_id}")
                    return

            slack_conn = await supabase.table("slack_connections") \
                .select("slack_team_id") \
                .eq("profile_id", row["profile_id"]) \
                .eq("is_active", True) \
                .execute_async()
            team_id = slack_conn.data[0]["slack_team_id"] if slack_conn.data else None
            enriched_payload = {
                **payload,
                "channel": {"id": row.get("slack_channel_id")},
                "message": {"ts": row.get("slack_message_ts")},
                "team": {"id": team_id},
            }
            await _select_role(detection_id, requisition_id, enriched_payload)
        else:
            await _select_role(detection_id, requisition_id, payload)


async def _get_detection(detection_id: str) -> dict:
    supabase = get_supabase_admin_client()
    result = await supabase.table("calendar_event_detections") \
        .select("*") \
        .eq("id", detection_id) \
        .execute_async()
    if not result.data:
        raise DetectionExpiredError(f"Detection {detection_id} not found")
    return result.data[0]


def _minimal_role_candidates(
    reqs: list[dict],
    cap: int = MAX_PERSISTED_ROLE_CANDIDATES,
) -> list[dict]:
    """Build the lightweight role-candidate payload stored in
    ``detection_signals._ui_state``. ``cap`` is applied after preserving input
    order so the caller's "newest first" sort carries through. A cap of 0 or
    negative disables truncation (used by tests / pure-render paths that want
    the full list)."""
    candidates = []
    for req in (reqs or []):
        if not req.get("id"):
            continue
        candidates.append({
            "id": str(req["id"]),
            "role_title": req.get("role_title", "Unknown"),
            "role_location": req.get("role_location", ""),
            "status": req.get("status", ""),
            "created_at": req.get("created_at", ""),
        })
    if cap and cap > 0 and len(candidates) > cap:
        candidates = candidates[:cap]
    return candidates


def _minimal_round_candidates(rounds: list[dict]) -> list[dict]:
    items = []
    for r in (rounds or []):
        if not r.get("id"):
            continue
        items.append({
            "id": str(r["id"]),
            "name": r.get("name", "Round"),
            "round_number": r.get("round_number"),
            "duration_minutes": r.get("duration_minutes", 45),
            "default_interviewer_emails": r.get("default_interviewer_emails") or [],
        })
    return items


def _read_ui_state(detection: dict) -> tuple[dict, dict]:
    signals = detection.get("detection_signals") or {}
    ui_state = signals.get("_ui_state") or {}
    if not isinstance(ui_state, dict):
        ui_state = {}
    stack = ui_state.get("state_stack")
    if not isinstance(stack, list):
        stack = []
    ui_state["state_stack"] = stack
    ui_state.setdefault("current_step", "detected")
    return signals, ui_state


def _snapshot_current_ui_state(ui_state: dict) -> dict | None:
    """Build a compact state_stack entry for navigation history.

    Codex Round 8: this MUST NOT snapshot `role_candidates` or
    `round_candidates`. Snapshotting them embeds up to
    MAX_PERSISTED_ROLE_CANDIDATES (100) role records per stack entry, and
    the stack retains the last 10 entries, so repeated Back/Change Role
    navigation can inflate `detection_signals` by ~1000 role rows and cause
    row-update writes to fail. Store only scalar pointers; the `_back_to_*`
    handlers already re-fetch candidates live from the DB on pop (see
    `_back_to_role` / `_back_to_round` fallback paths).
    """
    step = ui_state.get("current_step")
    if not step:
        return None
    snapshot = {"step": step}
    for key in (
        "selected_requisition_id",
        "selected_round_id",
        "role_title",
    ):
        if key in ui_state:
            snapshot[key] = ui_state.get(key)
    return snapshot


# Codex Round 8: hard cap on the serialized _ui_state payload (bytes).
# Exceeding this means something upstream regressed the snapshot shape or
# the candidate lists — we log + trim rather than silently let the DB
# update blow up on payload size.
_UI_STATE_MAX_SERIALIZED_BYTES = 64 * 1024  # 64 KiB


def _push_ui_state(ui_state: dict):
    snapshot = _snapshot_current_ui_state(ui_state)
    if not snapshot:
        return
    stack = ui_state.get("state_stack") or []
    stack.append(snapshot)
    ui_state["state_stack"] = stack[-10:]


def _pop_ui_state(ui_state: dict, step: str | None = None) -> dict | None:
    stack = ui_state.get("state_stack") or []
    if not stack:
        return None
    if step is None:
        item = stack.pop()
        ui_state["state_stack"] = stack
        return item
    original_stack = list(stack)
    while stack:
        item = stack.pop()
        if item.get("step") == step:
            ui_state["state_stack"] = stack
            return item
    ui_state["state_stack"] = original_stack
    return None


def _trim_ui_state_if_oversized(ui_state: dict) -> dict:
    """Defensive size guard for _ui_state before writing it back.

    Codex Round 8: the state-stack snapshot shape must stay compact
    (`_snapshot_current_ui_state` no longer copies candidate arrays), but
    `role_candidates` + `round_candidates` can still grow on the active
    step. If the serialized payload still exceeds
    `_UI_STATE_MAX_SERIALIZED_BYTES`, drop `state_stack` first (navigation
    history is recoverable from DB re-fetch on back), then trim
    `role_candidates`, then finally clear them entirely. We would rather
    lose some history than fail the row update and leave the user in a
    broken Slack flow.
    """
    if not isinstance(ui_state, dict):
        return ui_state

    def _size(obj: dict) -> int:
        try:
            return len(json.dumps(obj, default=str))
        except (TypeError, ValueError):
            # Unserializable object in state — return a large number so
            # we fall through to aggressive trimming.
            return _UI_STATE_MAX_SERIALIZED_BYTES * 2

    if _size(ui_state) <= _UI_STATE_MAX_SERIALIZED_BYTES:
        return ui_state

    trimmed = dict(ui_state)
    if trimmed.get("state_stack"):
        logger.warning(
            "Calendar Intelligence: _ui_state exceeds "
            f"{_UI_STATE_MAX_SERIALIZED_BYTES} bytes, dropping state_stack "
            "to avoid oversized row update"
        )
        trimmed["state_stack"] = []
        if _size(trimmed) <= _UI_STATE_MAX_SERIALIZED_BYTES:
            return trimmed

    role_candidates = trimmed.get("role_candidates")
    if isinstance(role_candidates, list) and len(role_candidates) > 10:
        logger.warning(
            "Calendar Intelligence: _ui_state still oversized after "
            "state_stack drop, truncating role_candidates to first 10"
        )
        trimmed["role_candidates"] = role_candidates[:10]
        if _size(trimmed) <= _UI_STATE_MAX_SERIALIZED_BYTES:
            return trimmed

    # Last resort — clear the large arrays entirely. Handlers will refetch
    # from DB on the next interaction.
    logger.error(
        "Calendar Intelligence: _ui_state still oversized after trims, "
        "clearing role_candidates and round_candidates"
    )
    trimmed["role_candidates"] = []
    trimmed["round_candidates"] = []
    return trimmed


async def _persist_ui_state(supabase, detection_id: str, signals: dict, ui_state: dict):
    # Codex Round 8: belt-and-suspenders size guard. The primary fix lives
    # in `_snapshot_current_ui_state` (no candidate arrays in stack); this
    # guard catches any future regression and degrades gracefully instead
    # of letting Supabase reject the update under a payload-size ceiling.
    trimmed = _trim_ui_state_if_oversized(ui_state)
    next_signals = dict(signals or {})
    next_signals["_ui_state"] = trimmed
    context_detection = {
        "detection_signals": next_signals,
        "detection_status": "notified",
    }
    next_signals = merge_interaction_context(
        next_signals,
        context_detection,
        role_title=str(trimmed.get("role_title") or ""),
        current_step=str(trimmed.get("current_step") or ""),
    )
    await supabase.table("calendar_event_detections") \
        .update({
            "detection_signals": next_signals,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }) \
        .eq("id", detection_id) \
        .execute_async()


async def _fetch_open_requisitions_for_detection(supabase, detection: dict) -> list[dict]:
    reqs_result = await supabase.table("requisitions") \
        .select("id, role_title, role_location, status, created_at") \
        .eq("created_by", detection["profile_id"]) \
        .in_("status", ["open", "active", "sourcing", "planned"]) \
        .is_("is_system_template", "false") \
        .is_("deleted_at", "null") \
        .order("created_at", desc=True) \
        .execute_async()
    return reqs_result.data or []


async def _fetch_requisitions_with_rounds_for_detection(
    supabase,
    detection: dict,
    req_ids: list[str] | None = None,
) -> list[dict]:
    query = supabase.table("requisitions") \
        .select("id, role_title, role_location, status, created_at") \
        .eq("created_by", detection["profile_id"]) \
        .in_("status", ["open", "active", "sourcing", "planned"]) \
        .is_("is_system_template", "false") \
        .is_("deleted_at", "null")
    if req_ids:
        query = query.in_("id", req_ids)

    reqs_result = await query.order("created_at", desc=True).execute_async()
    reqs = reqs_result.data or []
    if not reqs:
        return []

    rounds_result = await supabase.table("rounds") \
        .select("id, name, requisition_id, round_number, duration_minutes, default_interviewer_emails") \
        .in_("requisition_id", [r["id"] for r in reqs]) \
        .is_("deleted_at", "null") \
        .order("round_number") \
        .execute_async()
    rounds_by_req: dict[str, list[dict]] = {}
    for rd in (rounds_result.data or []):
        req_id = str(rd.get("requisition_id"))
        if not req_id:
            continue
        rounds_by_req.setdefault(req_id, []).append(rd)

    for req in reqs:
        req["rounds"] = rounds_by_req.get(str(req["id"]), [])
    return reqs


def _extract_role_match_req_ids(match_meta: dict | None) -> list[str]:
    if not isinstance(match_meta, dict):
        return []
    req_ids: list[str] = []
    scores = match_meta.get("scores")
    if isinstance(scores, dict):
        req_ids.extend(str(rid) for rid in scores.keys() if rid)
    elif isinstance(scores, list):
        for item in scores:
            if isinstance(item, dict) and item.get("requisition_id"):
                req_ids.append(str(item["requisition_id"]))
    for key in ("matched_requisition_id", "selected_requisition_id"):
        rid = match_meta.get(key)
        if rid:
            req_ids.append(str(rid))
    return req_ids


async def _build_detected_step_blocks(supabase, detection: dict) -> list[dict]:
    signals = detection.get("detection_signals") or {}
    if not isinstance(signals, dict):
        signals = {}

    if (
        detection.get("matched_candidate_round_id")
        and signals.get("untracked_capture")
        and str(signals.get("untracked_capture_mode") or "confirmed") != "preconfirm"
    ):
        return build_untracked_captured_blocks(
            detection,
            candidate_name=str(signals.get("untracked_capture_candidate_name") or ""),
            candidate_email=str(signals.get("untracked_capture_candidate_email") or ""),
        )

    match_meta = signals.get("_role_match")
    req_ids = []

    matched_req = detection.get("matched_requisition_id")
    if matched_req:
        req_ids.append(str(matched_req))
    req_ids.extend(_extract_role_match_req_ids(match_meta))
    req_ids = list(dict.fromkeys(r for r in req_ids if r))

    reqs = await _fetch_requisitions_with_rounds_for_detection(
        supabase, detection, req_ids=req_ids or None
    )
    if not reqs and req_ids:
        reqs = await _fetch_requisitions_with_rounds_for_detection(supabase, detection, req_ids=None)

    if reqs:
        return build_detection_blocks(
            detection,
            reqs,
            match_meta if isinstance(match_meta, dict) else None,
        )

    org_id = str(detection.get("organization_id") or "")
    profile_id = str(detection.get("profile_id") or "")
    if org_id and profile_id and is_untracked_capture_enabled():
        auto_join_enabled, auto_join_source = await get_auto_join_untracked_preference(
            supabase,
            profile_id=profile_id,
            organization_id=org_id,
        )
        if auto_join_enabled:
            capture_result = await capture_untracked_interview(
                supabase,
                detection,
                _link_bot_to_candidate_round,
            )
            if capture_result:
                return build_untracked_captured_blocks(
                    detection,
                    candidate_name=capture_result.candidate_name,
                    candidate_email=capture_result.candidate_email,
                )
        else:
            logger.info(
                "Calendar Intelligence: skipping untracked auto-capture for detection=%s source=%s",
                detection.get("id"),
                auto_join_source,
            )

    return build_no_req_blocks(detection, "no_reqs")


async def _fetch_rounds_for_requisition(supabase, requisition_id: str) -> list[dict]:
    rounds_result = await supabase.table("rounds") \
        .select("id, name, round_number, duration_minutes, default_interviewer_emails") \
        .eq("requisition_id", requisition_id) \
        .is_("deleted_at", "null") \
        .order("round_number") \
        .execute_async()
    return rounds_result.data or []


async def _select_role(detection_id: str, requisition_id: Optional[str], payload: dict):
    supabase = get_supabase_admin_client()
    detection = await _get_detection(detection_id)
    current = detection["detection_status"]
    signals, ui_state = _read_ui_state(detection)

    if current in SELECT_LOCKED_STATUSES:
        raise DetectionAlreadyProcessedError()

    if not requisition_id:
        if current == "awaiting_confirm":
            rollback = await supabase.table("calendar_event_detections") \
                .update({
                    "detection_status": "awaiting_role",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }) \
                .eq("id", detection_id) \
                .eq("detection_status", "awaiting_confirm") \
                .execute_async()
            if not rollback.data:
                raise DetectionAlreadyProcessedError()
            current = "awaiting_role"

        # Always fetch live open requisitions — the cached role_candidates may be
        # a truncated subset (top 25 seeded at notification time) and using it as
        # the authoritative list would hide valid roles and push users toward the
        # wrong requisition. Cache is display/ranking hint only.
        reqs = await _fetch_open_requisitions_for_detection(supabase, detection)
        if not reqs:
            await _update_slack_message(payload, build_error_blocks("No open roles found."))
            return

        _push_ui_state(ui_state)
        ui_state["current_step"] = "role_select"
        ui_state["selected_requisition_id"] = None
        ui_state["selected_round_id"] = None
        ui_state["role_title"] = ""
        ui_state["role_candidates"] = _minimal_role_candidates(reqs)
        ui_state["round_candidates"] = []
        await _persist_ui_state(supabase, detection_id, signals, ui_state)

        if len(reqs) >= 4 and len(reqs) <= 100:
            trigger_id = payload.get("trigger_id")
            if trigger_id:
                service = get_slack_service()
                team_data = payload.get("team", {})
                team_id = team_data.get("id") if isinstance(team_data, dict) else team_data
                bot_token = await service.get_bot_token_for_team(team_id)
                modal = build_role_modal(detection_id, reqs)
                await service.open_modal(bot_token, trigger_id, modal, team_id=team_id)
                return

        blocks = build_role_selection_step_blocks(detection, reqs)
        await _update_slack_message(payload, blocks)
        return

    req_result = await supabase.table("requisitions") \
        .select("id, role_title, created_by") \
        .eq("id", requisition_id) \
        .is_("is_system_template", "false") \
        .is_("deleted_at", "null") \
        .execute_async()
    if not req_result.data:
        raise RequisitionDeletedError()
    if str(req_result.data[0].get("created_by")) != str(detection["profile_id"]):
        raise CalendarIntelligenceError("Role does not belong to you.")

    new_status = transition_detection_status(current, "awaiting_round") if current != "awaiting_round" else current
    now = datetime.now(timezone.utc).isoformat()
    role_cas = await supabase.table("calendar_event_detections") \
        .update({
            "matched_requisition_id": requisition_id,
            "detection_status": new_status,
            "responded_at": now,
            "updated_at": now,
        }) \
        .eq("id", detection_id) \
        .eq("detection_status", current) \
        .execute_async()
    if not role_cas.data:
        raise DetectionAlreadyProcessedError()

    rounds = await _fetch_rounds_for_requisition(supabase, requisition_id)

    if not rounds:
        org_id = str(detection.get("organization_id") or "")
        profile_id = str(detection.get("profile_id") or "")
        if org_id and profile_id and is_untracked_capture_enabled():
            auto_join_enabled, auto_join_source = await get_auto_join_untracked_preference(
                supabase,
                profile_id=profile_id,
                organization_id=org_id,
            )
            if auto_join_enabled:
                capture_result = await capture_untracked_interview(
                    supabase,
                    detection,
                    _link_bot_to_candidate_round,
                )
                if capture_result:
                    await _update_slack_message(
                        payload,
                        build_untracked_captured_blocks(
                            detection,
                            candidate_name=capture_result.candidate_name,
                            candidate_email=capture_result.candidate_email,
                        ),
                    )
                    return
            else:
                logger.info(
                    "Calendar Intelligence: role-selected no-rounds capture skipped "
                    "for detection=%s source=%s",
                    detection.get("id"),
                    auto_join_source,
                )

        await _update_slack_message(payload, build_error_blocks("No rounds found for this role."))
        return

    role_title = req_result.data[0].get("role_title", "")
    interviewer_status = "unset"
    for r in rounds:
        status = check_interviewer_match(detection, r)
        if status == "match":
            interviewer_status = "match"
            break
        elif status == "mismatch":
            interviewer_status = "mismatch"

    previous_step = ui_state.get("current_step", "")
    _push_ui_state(ui_state)
    ui_state["current_step"] = "round_select"
    ui_state["selected_requisition_id"] = str(requisition_id)
    ui_state["selected_round_id"] = None
    ui_state["role_title"] = role_title
    ui_state["round_candidates"] = _minimal_round_candidates(rounds)
    if not ui_state.get("role_candidates"):
        ui_state["role_candidates"] = _minimal_role_candidates(await _fetch_open_requisitions_for_detection(supabase, detection))
    await _persist_ui_state(supabase, detection_id, signals, ui_state)

    blocks = build_round_selection_blocks(
        detection_id, rounds, interviewer_status,
        detection=detection, role_title=role_title, show_back_to_role=True,
        back_action_id=("cal_intel_back_role" if previous_step == "role_select" else "cal_intel_back_detected"),
        back_button_text=("Back to Roles" if previous_step == "role_select" else "Back"),
    )
    await _update_slack_message(payload, blocks)


async def _select_round(detection_id: str, round_id: str, payload: dict):
    if not round_id:
        await _update_slack_message(payload, build_error_blocks("Please select a round first."))
        return

    supabase = get_supabase_admin_client()
    detection = await _get_detection(detection_id)
    current = detection["detection_status"]
    signals, ui_state = _read_ui_state(detection)

    if current in SELECT_LOCKED_STATUSES:
        raise DetectionAlreadyProcessedError()

    req_id = detection.get("matched_requisition_id")
    role_title = ui_state.get("role_title", "")
    if req_id and not role_title:
        req = await supabase.table("requisitions").select("role_title").eq("id", req_id).execute_async()
        role_title = req.data[0]["role_title"] if req.data else ""

    round_result = await supabase.table("rounds") \
        .select("id, name, duration_minutes, requisition_id") \
        .eq("id", round_id) \
        .is_("deleted_at", "null") \
        .execute_async()
    if not round_result.data:
        raise RoundDeletedError()
    round_data = round_result.data[0]

    if req_id and str(round_data.get("requisition_id")) != str(req_id):
        raise CalendarIntelligenceError("Round does not belong to the selected role.")

    new_status = transition_detection_status(current, "awaiting_confirm") if current != "awaiting_confirm" else current
    cas = await supabase.table("calendar_event_detections") \
        .update({
            "detection_status": new_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }) \
        .eq("id", detection_id) \
        .eq("detection_status", current) \
        .execute_async()
    if not cas.data:
        raise DetectionAlreadyProcessedError()

    _push_ui_state(ui_state)
    ui_state["current_step"] = "review"
    ui_state["selected_round_id"] = str(round_id)
    ui_state["role_title"] = role_title
    _sync_selected_candidate_email(ui_state, detection)
    await _persist_ui_state(supabase, detection_id, signals, ui_state)

    rounds_for_req = ui_state.get("round_candidates") or []
    # Keep back navigation consistent: review -> round step, even when only one round exists.
    show_back_to_round = len(rounds_for_req) >= 1
    blocks = _build_review_blocks_with_candidate_disambiguation(
        detection=detection,
        role_title=role_title,
        round_data=round_data,
        show_back_to_round=show_back_to_round,
        ui_state=ui_state,
    )
    await _update_slack_message(payload, blocks)


async def _select_candidate(detection_id: str, candidate_email: str, payload: dict):
    supabase = get_supabase_admin_client()
    detection = await _get_detection(detection_id)
    current = detection["detection_status"]
    signals, ui_state = _read_ui_state(detection)

    if current in SELECT_LOCKED_STATUSES:
        raise DetectionAlreadyProcessedError()

    candidate_options = _candidate_options_from_detection(detection)
    if len(candidate_options) <= 1:
        return

    selected_email = _normalize_attendee_email(candidate_email)
    valid_emails = {opt["email"] for opt in candidate_options}
    if selected_email not in valid_emails:
        selected_email = ""
    ui_state["selected_candidate_email"] = selected_email
    await _persist_ui_state(supabase, detection_id, signals, ui_state)

    selected_round_id = str(ui_state.get("selected_round_id") or "")
    if not selected_round_id:
        await _update_slack_message(payload, build_error_blocks("Please select a round first."))
        return

    round_result = await supabase.table("rounds") \
        .select("id, name, duration_minutes, requisition_id") \
        .eq("id", selected_round_id) \
        .is_("deleted_at", "null") \
        .execute_async()
    if not round_result.data:
        raise RoundDeletedError()
    round_data = round_result.data[0]

    req_id = detection.get("matched_requisition_id") or round_data.get("requisition_id")
    role_title = str(ui_state.get("role_title") or "")
    if req_id and not role_title:
        req = await supabase.table("requisitions").select("role_title").eq("id", req_id).execute_async()
        role_title = req.data[0]["role_title"] if req.data else ""

    rounds_for_req = ui_state.get("round_candidates") or []
    blocks = _build_review_blocks_with_candidate_disambiguation(
        detection=detection,
        role_title=role_title,
        round_data=round_data,
        show_back_to_round=len(rounds_for_req) >= 1,
        ui_state=ui_state,
        validation_error=(
            "Please select the candidate before confirming this interview."
            if not selected_email
            else ""
        ),
    )
    await _update_slack_message(payload, blocks)


async def _back_to_role(detection_id: str, payload: dict):
    supabase = get_supabase_admin_client()
    detection = await _get_detection(detection_id)
    signals, ui_state = _read_ui_state(detection)
    state = _pop_ui_state(ui_state, step="role_select")
    if not state:
        await _back_to_detected(detection_id, payload)
        return

    # Always fetch live — stacked/cached role_candidates can be a truncated top-N
    # subset; relying on it would hide newly created roles or miss roles from
    # the original seed. Codex adversarial review: role reselection must see
    # every open requisition the recruiter owns.
    live_reqs = await _fetch_open_requisitions_for_detection(supabase, detection)
    if not live_reqs:
        await _update_slack_message(payload, build_error_blocks("No open roles found."))
        return

    if detection.get("detection_status") == "awaiting_confirm":
        await supabase.table("calendar_event_detections") \
            .update({
                "detection_status": "awaiting_role",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }) \
            .eq("id", detection_id) \
            .eq("detection_status", "awaiting_confirm") \
            .execute_async()

    ui_state["current_step"] = "role_select"
    ui_state["selected_requisition_id"] = None
    ui_state["selected_round_id"] = None
    ui_state["role_title"] = ""
    # Persist a capped subset (Codex Round 4: keep detection_signals row small)
    # while passing the full live list to the renderer so the >100 "go to
    # dashboard" path still fires for very large tenants.
    ui_state["role_candidates"] = _minimal_role_candidates(live_reqs)
    ui_state["round_candidates"] = []
    await _persist_ui_state(supabase, detection_id, signals, ui_state)

    blocks = build_role_selection_step_blocks(detection, live_reqs)
    await _update_slack_message(payload, blocks)


async def _back_to_detected(detection_id: str, payload: dict):
    supabase = get_supabase_admin_client()
    detection = await _get_detection(detection_id)
    signals, ui_state = _read_ui_state(detection)
    _pop_ui_state(ui_state, step="detected")

    if detection.get("detection_status") == "awaiting_confirm":
        await supabase.table("calendar_event_detections") \
            .update({
                "detection_status": "awaiting_round",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }) \
            .eq("id", detection_id) \
            .eq("detection_status", "awaiting_confirm") \
            .execute_async()

    ui_state["current_step"] = "detected"
    ui_state["selected_round_id"] = None
    ui_state["round_candidates"] = []
    await _persist_ui_state(supabase, detection_id, signals, ui_state)

    refreshed = dict(detection)
    refreshed["detection_signals"] = {**(signals or {}), "_ui_state": ui_state}
    blocks = await _build_detected_step_blocks(supabase, refreshed)
    await _update_slack_message(payload, blocks)


async def _back_to_round(detection_id: str, payload: dict):
    supabase = get_supabase_admin_client()
    detection = await _get_detection(detection_id)
    signals, ui_state = _read_ui_state(detection)
    state = _pop_ui_state(ui_state, step="round_select")

    req_id = None
    role_title = ""
    rounds = []
    if state:
        req_id = state.get("selected_requisition_id")
        role_title = state.get("role_title", "")
        rounds = state.get("round_candidates") or []
        if not rounds and req_id:
            rounds = _minimal_round_candidates(await _fetch_rounds_for_requisition(supabase, req_id))
    else:
        req_id = ui_state.get("selected_requisition_id") or detection.get("matched_requisition_id")
        role_title = ui_state.get("role_title", "")
        if req_id:
            rounds = _minimal_round_candidates(await _fetch_rounds_for_requisition(supabase, req_id))

    if not rounds or not req_id:
        await _back_to_role(detection_id, payload)
        return

    if detection.get("detection_status") == "awaiting_confirm":
        await supabase.table("calendar_event_detections") \
            .update({
                "detection_status": "awaiting_round",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }) \
            .eq("id", detection_id) \
            .eq("detection_status", "awaiting_confirm") \
            .execute_async()

    ui_state["current_step"] = "round_select"
    ui_state["selected_requisition_id"] = str(req_id)
    ui_state["selected_round_id"] = None
    ui_state["role_title"] = role_title
    ui_state["round_candidates"] = rounds
    await _persist_ui_state(supabase, detection_id, signals, ui_state)

    interviewer_status = "unset"
    for r in rounds:
        status = check_interviewer_match(detection, r)
        if status == "match":
            interviewer_status = "match"
            break
        if status == "mismatch":
            interviewer_status = "mismatch"

    stack = ui_state.get("state_stack") or []
    has_role_step = any(isinstance(item, dict) and item.get("step") == "role_select" for item in stack)
    back_action_id = "cal_intel_back_role" if has_role_step else "cal_intel_back_detected"
    back_button_text = "Back to Roles" if has_role_step else "Back"

    blocks = build_round_selection_blocks(
        detection_id=detection_id,
        rounds=rounds,
        interviewer_status=interviewer_status,
        detection=detection,
        role_title=role_title,
        show_back_to_role=True,
        back_action_id=back_action_id,
        back_button_text=back_button_text,
    )
    await _update_slack_message(payload, blocks)


async def _confirm(
    detection_id: str,
    round_id: str,
    payload: dict,
    role_title: str = "",
    force_import_override: bool = False,
):
    if not round_id:
        await _update_slack_message(payload, build_error_blocks("Please select a round first."))
        return

    supabase = get_supabase_admin_client()
    detection = await _get_detection(detection_id)
    current = detection["detection_status"]
    _, ui_state = _read_ui_state(detection)

    if current in CONFIRM_LOCKED_STATUSES:
        raise DetectionAlreadyProcessedError()
    if current not in CONFIRMABLE_STATUSES:
        raise DetectionAlreadyProcessedError()

    cas_lock = await supabase.table("calendar_event_detections") \
        .update({"detection_status": "confirming", "updated_at": datetime.now(timezone.utc).isoformat()}) \
        .eq("id", detection_id) \
        .eq("detection_status", current) \
        .execute_async()
    if not cas_lock.data:
        raise DetectionAlreadyProcessedError()

    candidate_round_id = None
    candidate_id = None
    candidate_was_created = False
    cr_was_created = False
    prior_round_state = None
    candidate_email = ""
    candidate_name = ""
    interviewer_email_resolved = None
    imported_via_copy = False
    detection_signals = detection.get("detection_signals") or {}
    if not isinstance(detection_signals, dict):
        detection_signals = {}
    is_untracked_promotion = bool(detection_signals.get("untracked_capture"))
    prior_untracked_round_id = (
        str(detection.get("matched_candidate_round_id") or "")
        if is_untracked_promotion
        else ""
    )

    try:
        round_result = await supabase.table("rounds") \
            .select("id, name, requisition_id, round_number, default_interviewer_emails") \
            .eq("id", round_id) \
            .is_("deleted_at", "null") \
            .execute_async()
        if not round_result.data:
            raise RoundDeletedError()

        round_data = round_result.data[0]
        requisition_id = round_data["requisition_id"]

        try:
            user_conn = await supabase.table("user_connections") \
                .select("provider_email") \
                .eq("profile_id", detection["profile_id"]) \
                .eq("provider", "google_calendar") \
                .eq("is_active", True) \
                .limit(1) \
                .execute_async()
            recruiter_email = user_conn.data[0]["provider_email"] if user_conn.data else None
            from app.services.calendar_intelligence_service import resolve_interviewer_email
            interviewer_email_resolved = resolve_interviewer_email(
                detection.get("internal_attendees", []),
                round_data,
                recruiter_email or "",
            )
        except Exception as e:
            logger.warning(f"Cal Intel confirm: could not resolve interviewer email for detection={detection_id}: {e}")
        matched_req = detection.get("matched_requisition_id")
        if matched_req and str(matched_req) != str(requisition_id):
            raise CalendarIntelligenceError("Round does not belong to the selected role.")

        req_owner = await supabase.table("requisitions") \
            .select("created_by") \
            .eq("id", requisition_id) \
            .execute_async()
        if req_owner.data and str(req_owner.data[0].get("created_by")) != str(detection["profile_id"]):
            raise CalendarIntelligenceError("Role does not belong to you.")

        if is_untracked_promotion and _event_start_has_passed(detection):
            if not prior_untracked_round_id:
                raise CalendarIntelligenceError(
                    "Unable to map this untracked interview because the source interview record is missing."
                )

            import_service = UntrackedImportService(supabase)
            try:
                import_result = await import_service.import_untracked_interview(
                    req_id=str(requisition_id),
                    source_candidate_round_id=str(prior_untracked_round_id),
                    target_round_id=str(round_id),
                    org_id=str(detection.get("organization_id") or ""),
                    imported_by_user_id=str(detection.get("profile_id") or "") or None,
                    override_existing_round=force_import_override,
                )
            except UntrackedImportError as import_exc:
                conflict_detail = _extract_existing_round_conflict_detail(import_exc.detail)
                if conflict_detail and not force_import_override:
                    await supabase.table("calendar_event_detections") \
                        .update({"detection_status": current, "updated_at": datetime.now(timezone.utc).isoformat()}) \
                        .eq("id", detection_id) \
                        .eq("detection_status", "confirming") \
                        .execute_async()

                    role_title_for_warning = role_title or str(ui_state.get("role_title") or "")
                    if not role_title_for_warning:
                        req_for_title = await supabase.table("requisitions") \
                            .select("role_title") \
                            .eq("id", requisition_id) \
                            .limit(1) \
                            .execute_async()
                        role_title_for_warning = req_for_title.data[0]["role_title"] if req_for_title.data else ""

                    warning_blocks = _build_untracked_import_conflict_blocks(
                        detection,
                        round_id=str(round_id),
                        role_title=role_title_for_warning,
                        round_data=round_data,
                        detail=conflict_detail,
                    )
                    await _update_slack_message(payload, warning_blocks)
                    return

                if isinstance(import_exc.detail, dict):
                    raise CalendarIntelligenceError(
                        str(import_exc.detail.get("message") or "Could not import this interview.")
                    ) from import_exc
                raise CalendarIntelligenceError(str(import_exc.detail)) from import_exc

            candidate_round_id = str(import_result.get("target_candidate_round_id") or "")
            candidate_id = str(import_result.get("target_candidate_id") or "")
            candidate_was_created = bool(import_result.get("candidate_created"))
            imported_via_copy = True

            if not candidate_round_id:
                raise CalendarIntelligenceError("Import completed but target round mapping was missing.")

            if candidate_id:
                target_candidate_result = await supabase.table("candidates") \
                    .select("name, email") \
                    .eq("id", candidate_id) \
                    .limit(1) \
                    .execute_async()
                if target_candidate_result.data:
                    candidate_name = str(target_candidate_result.data[0].get("name") or "")
                    candidate_email = str(target_candidate_result.data[0].get("email") or "")

        if not imported_via_copy:
            external = detection.get("external_attendees") or []
            if len(external) > 1:
                candidate_options = _candidate_options_from_detection(detection)
                selected_candidate_email = _selected_candidate_email(ui_state, candidate_options)
                if selected_candidate_email:
                    external = [
                        attendee
                        for attendee in external
                        if _normalize_attendee_email(attendee.get("email")) == selected_candidate_email
                    ]

            if len(external) > 1:
                await supabase.table("calendar_event_detections") \
                    .update({"detection_status": current, "updated_at": datetime.now(timezone.utc).isoformat()}) \
                    .eq("id", detection_id) \
                    .eq("detection_status", "confirming") \
                    .execute_async()

                role_title_for_review = role_title
                if not role_title_for_review:
                    req_for_title = await supabase.table("requisitions") \
                        .select("role_title") \
                        .eq("id", requisition_id) \
                        .limit(1) \
                        .execute_async()
                    role_title_for_review = req_for_title.data[0]["role_title"] if req_for_title.data else ""

                rounds_for_req = ui_state.get("round_candidates") or []
                preview_detection = dict(detection)
                preview_signals = dict(detection_signals or {})
                preview_signals["_ui_state"] = ui_state
                preview_detection["detection_signals"] = preview_signals
                review_blocks = _build_review_blocks_with_candidate_disambiguation(
                    detection=preview_detection,
                    role_title=role_title_for_review,
                    round_data=round_data,
                    show_back_to_round=len(rounds_for_req) >= 1,
                    ui_state=ui_state,
                    validation_error="Please select the candidate before confirming this interview.",
                )
                await _update_slack_message(
                    payload,
                    review_blocks,
                )
                return

            candidate_email = external[0].get("email", "") if external else ""
            candidate_name = ""
            if candidate_email:
                from app.services.calendar_intelligence_service import resolve_candidate_name
                candidate_name = resolve_candidate_name(detection, candidate_email)
            elif external:
                candidate_name = external[0].get("display_name") or ""

            if candidate_email:
                existing = await supabase.table("candidates") \
                    .select("id") \
                    .eq("requisition_id", requisition_id) \
                    .eq("email", candidate_email.lower()) \
                    .is_("deleted_at", "null") \
                    .execute_async()
                if existing.data:
                    candidate_id = existing.data[0]["id"]
                else:
                    from app.services.candidate_service import get_candidate_service
                    org_id = detection.get("organization_id")
                    try:
                        cand_svc = get_candidate_service()
                        result = await cand_svc.add_candidate(
                            requisition_id=requisition_id,
                            org_id=org_id,
                            name=candidate_name or "Unknown",
                            email=candidate_email.lower(),
                        )
                        candidate_id = result["candidate"]["id"]
                        candidate_was_created = True
                    except ValueError as e:
                        if "already exists" in str(e):
                            re_check = await supabase.table("candidates") \
                                .select("id") \
                                .eq("requisition_id", requisition_id) \
                                .eq("email", candidate_email.lower()) \
                                .is_("deleted_at", "null") \
                                .execute_async()
                            if re_check.data:
                                candidate_id = re_check.data[0]["id"]
                        else:
                            raise

            if candidate_id:
                existing_cr = await supabase.table("candidate_rounds") \
                    .select("id, status, meeting_url, scheduled_at, interviewer_email") \
                    .eq("candidate_id", candidate_id) \
                    .eq("round_id", round_id) \
                    .execute_async()
                if existing_cr.data:
                    cr_row = existing_cr.data[0]
                    cr_status = cr_row.get("status")
                    if cr_status in ("completed", "in_progress"):
                        raise CalendarIntelligenceError(
                            f"Round already {cr_status} for this candidate. "
                            "Please select a different round."
                        )
                    else:
                        candidate_round_id = cr_row["id"]
                        prior_round_state = {
                            "status": cr_status,
                            "meeting_url": cr_row.get("meeting_url"),
                            "scheduled_at": cr_row.get("scheduled_at"),
                            "interviewer_email": cr_row.get("interviewer_email"),
                        }
                        if cr_status in ("pending", "scheduled", "cancelled"):
                            update_data = {
                                "status": "scheduled",
                                "meeting_url": detection.get("meeting_url"),
                                "scheduled_at": detection.get("event_start"),
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            }
                            if interviewer_email_resolved:
                                update_data["interviewer_email"] = interviewer_email_resolved
                            cr_update = await supabase.table("candidate_rounds") \
                                .update(update_data) \
                                .eq("id", candidate_round_id) \
                                .in_("status", ["pending", "scheduled", "cancelled"]) \
                                .execute_async()
                            if not cr_update.data:
                                raise CalendarIntelligenceError(
                                    "Round status changed concurrently. Please try again."
                                )
                else:
                    insert_data = {
                        "candidate_id": candidate_id,
                        "round_id": round_id,
                        "status": "scheduled",
                        "meeting_url": detection.get("meeting_url"),
                        "scheduled_at": detection.get("event_start"),
                    }
                    if interviewer_email_resolved:
                        insert_data["interviewer_email"] = interviewer_email_resolved
                    cr_result = await supabase.table("candidate_rounds").insert(insert_data).execute_async()
                    if cr_result.data:
                        cr_data = cr_result.data[0] if isinstance(cr_result.data, list) else cr_result.data
                        candidate_round_id = cr_data["id"]
                        cr_was_created = True

        if not candidate_round_id:
            raise CalendarIntelligenceError("Could not create interview round. Please set up from the dashboard.")

        if not imported_via_copy:
            bot_linked = await _link_detection_bot_for_confirm(
                detection,
                candidate_round_id,
                supabase,
            )
            if not bot_linked:
                raise BotDeploymentError("Failed to deploy or link recording bot")

        settings = get_settings()
        undo_expires = (datetime.now(timezone.utc) + timedelta(minutes=settings.CALENDAR_INTELLIGENCE_UNDO_GRACE_MINUTES)).isoformat()
        now = datetime.now(timezone.utc).isoformat()

        if (
            prior_untracked_round_id
            and str(prior_untracked_round_id) != str(candidate_round_id)
        ):
            await supabase.table("candidate_rounds") \
                .update({"status": "cancelled", "updated_at": now}) \
                .eq("id", prior_untracked_round_id) \
                .in_("status", ["pending", "scheduled"]) \
                .execute_async()

        undo_metadata = {
            "cr_was_created": cr_was_created,
            "prior_round_state": prior_round_state,
        }

        existing_signals = detection.get("detection_signals") or {}
        if not isinstance(existing_signals, dict):
            existing_signals = {}
        if is_untracked_promotion:
            existing_signals["untracked_capture"] = False
            existing_signals["untracked_capture_promoted"] = True
            existing_signals["untracked_capture_promoted_at"] = now
            existing_signals["untracked_capture_promoted_from_candidate_round_id"] = prior_untracked_round_id or None
            existing_signals["untracked_capture_promoted_to_candidate_round_id"] = str(candidate_round_id)
        ui_state = existing_signals.get("_ui_state") or {}
        if not isinstance(ui_state, dict):
            ui_state = {}
        ui_state["current_step"] = "confirmed"
        ui_state["state_stack"] = []
        existing_signals["_ui_state"] = ui_state
        existing_signals["_undo_metadata"] = undo_metadata
        existing_signals["user_selected_req_id"] = str(requisition_id)
        context_detection = dict(detection)
        context_detection["detection_signals"] = existing_signals
        context_detection["detection_status"] = "confirmed"
        existing_signals = merge_interaction_context(
            existing_signals,
            context_detection,
            role_title=role_title,
            round_name=round_data.get("name", "Round"),
            candidate_name=candidate_name or "",
            candidate_email=candidate_email or "",
            interviewer_email=interviewer_email_resolved or "",
            current_step="confirmed",
        )

        final_cas = await supabase.table("calendar_event_detections") \
            .update({
                "detection_status": "confirmed",
                "matched_requisition_id": requisition_id,
                "matched_candidate_id": str(candidate_id) if candidate_id else None,
                "matched_candidate_round_id": str(candidate_round_id) if candidate_round_id else None,
                "candidate_was_created": candidate_was_created,
                "detection_signals": existing_signals,
                "undo_expires_at": undo_expires,
                "responded_at": now,
                "updated_at": now,
            }) \
            .eq("id", detection_id) \
            .eq("detection_status", "confirming") \
            .execute_async()

        if not final_cas.data:
            logger.error(f"Calendar Intelligence: final CAS failed for {detection_id} — confirming state was stolen")
            raise DetectionAlreadyProcessedError()

    except Exception:
        now_rollback = datetime.now(timezone.utc).isoformat()
        if cr_was_created and candidate_round_id:
            await supabase.table("candidate_rounds") \
                .update({"status": "cancelled", "updated_at": now_rollback}) \
                .eq("id", candidate_round_id) \
                .in_("status", ["pending", "scheduled"]) \
                .execute_async()
        elif prior_round_state and candidate_round_id:
            restore = {"updated_at": now_rollback}
            for f in ("status", "meeting_url", "scheduled_at", "interviewer_email"):
                if f in prior_round_state:
                    restore[f] = prior_round_state[f]
            await supabase.table("candidate_rounds") \
                .update(restore) \
                .eq("id", candidate_round_id) \
                .in_("status", ["pending", "scheduled"]) \
                .execute_async()
        if candidate_was_created and candidate_id:
            active_rounds = await supabase.table("candidate_rounds") \
                .select("id") \
                .eq("candidate_id", str(candidate_id)) \
                .in_("status", ["pending", "scheduled", "in_progress", "completed"]) \
                .limit(1) \
                .execute_async()
            if not active_rounds.data:
                await supabase.table("candidates") \
                    .update({"deleted_at": now_rollback}) \
                    .eq("id", str(candidate_id)) \
                    .is_("deleted_at", "null") \
                    .execute_async()
        try:
            rollback_bots = await supabase.table("recall_bots") \
                .select("id, recall_bot_id, status") \
                .eq("detection_id", detection_id) \
                .execute_async()
            for bot in (rollback_bots.data or []):
                if bot.get("status") in BOT_SPINUP_STATUSES:
                    try:
                        from app.services.recall_service import get_recall_service
                        await get_recall_service().delete_bot(bot["recall_bot_id"])
                    except Exception:
                        pass
        except Exception:
            pass
        await supabase.table("calendar_event_detections") \
            .update({"detection_status": current, "updated_at": now_rollback}) \
            .eq("id", detection_id) \
            .eq("detection_status", "confirming") \
            .execute_async()
        raise

    round_name = round_data.get("name", "Round")
    if not role_title:
        req_id = detection.get("matched_requisition_id") or round_data.get("requisition_id")
        if req_id:
            req_for_title = await supabase.table("requisitions").select("role_title").eq("id", req_id).execute_async()
            role_title = req_for_title.data[0]["role_title"] if req_for_title.data else ""
    blocks = build_confirmation_blocks(
        detection,
        candidate_name or candidate_email,
        round_name,
        role_title,
        candidate_email=candidate_email,
        interviewer_email=interviewer_email_resolved or "",
    )
    await _update_slack_message(payload, blocks)
    logger.info(f"Calendar Intelligence: confirmed detection={detection_id} candidate={candidate_id}")


async def _cancel_detection_bots(detection_id: str, supabase):
    bot_rows = await supabase.table("recall_bots") \
        .select("id, recall_bot_id, status") \
        .eq("detection_id", detection_id) \
        .in_("status", ["created", "joining", "in_waiting_room"]) \
        .execute_async()
    for bot in (bot_rows.data or []):
        try:
            from app.services.recall_service import get_recall_service
            await get_recall_service().delete_bot(bot["recall_bot_id"])
            await supabase.table("recall_bots") \
                .update({"status": "cancelled"}) \
                .eq("id", bot["id"]) \
                .execute_async()
        except Exception as e:
            logger.warning(f"Calendar Intelligence: cancel bot failed on dismiss: {e}")


async def _dismiss(detection_id: str, payload: dict):
    detection = await _get_detection(detection_id)
    current = detection["detection_status"]
    if current in TERMINAL_STATUSES:
        raise DetectionAlreadyProcessedError()

    supabase = get_supabase_admin_client()
    await _cancel_detection_bots(detection_id, supabase)

    signals, ui_state = _read_ui_state(detection)
    ui_state["current_step"] = "dismissed"
    ui_state["state_stack"] = []
    signals["_ui_state"] = ui_state
    context_detection = dict(detection)
    context_detection["detection_signals"] = signals
    context_detection["detection_status"] = "dismissed"
    signals = merge_interaction_context(
        signals,
        context_detection,
        current_step="dismissed",
    )
    now = datetime.now(timezone.utc).isoformat()
    cas_result = await supabase.table("calendar_event_detections") \
        .update({
            "detection_status": "dismissed",
            "detection_signals": signals,
            "responded_at": now,
            "updated_at": now,
        }) \
        .eq("id", detection_id) \
        .eq("detection_status", current) \
        .execute_async()
    if not cas_result.data:
        raise DetectionAlreadyProcessedError()

    await _update_slack_message(payload, [
        _build_context_header(detection, step_override="dismissed"),
        {"type": "section", "block_id": "cal_intel_dismissed",
         "text": {"type": "mrkdwn", "text": ":no_entry_sign: Dismissed — bot cancelled"}},
        build_open_in_app_action_block(detection, "dismissed"),
    ])


async def _not_interview(detection_id: str, payload: dict):
    detection = await _get_detection(detection_id)
    current = detection["detection_status"]
    if current in TERMINAL_STATUSES:
        raise DetectionAlreadyProcessedError()

    supabase = get_supabase_admin_client()
    await _cancel_detection_bots(detection_id, supabase)

    signals, ui_state = _read_ui_state(detection)
    ui_state["current_step"] = "not_interview"
    ui_state["state_stack"] = []
    signals["_ui_state"] = ui_state
    context_detection = dict(detection)
    context_detection["detection_signals"] = signals
    context_detection["detection_status"] = "not_interview"
    signals = merge_interaction_context(
        signals,
        context_detection,
        current_step="not_interview",
    )
    now = datetime.now(timezone.utc).isoformat()
    cas_result = await supabase.table("calendar_event_detections") \
        .update({
            "detection_status": "not_interview",
            "detection_signals": signals,
            "responded_at": now,
            "updated_at": now,
        }) \
        .eq("id", detection_id) \
        .eq("detection_status", current) \
        .execute_async()
    if not cas_result.data:
        raise DetectionAlreadyProcessedError()

    await _update_slack_message(payload, [
        _build_context_header(detection, step_override="not_interview"),
        {"type": "section", "block_id": "cal_intel_not_interview",
         "text": {"type": "mrkdwn", "text": ":spiral_note_pad: Not an interview — bot cancelled"}},
        build_open_in_app_action_block(detection, "not_interview"),
    ])


async def _undo(detection_id: str, payload: dict):
    detection = await _get_detection(detection_id)
    if detection["detection_status"] != "confirmed":
        raise DetectionAlreadyProcessedError()

    undo_expires = detection.get("undo_expires_at")
    if undo_expires:
        expires = datetime.fromisoformat(undo_expires)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires:
            raise UndoExpiredError()

    supabase = get_supabase_admin_client()
    cr_id = detection.get("matched_candidate_round_id")
    undo_meta = (detection.get("detection_signals") or {}).get("_undo_metadata", {})
    cr_was_created = undo_meta.get("cr_was_created", False)
    prior_round_state = undo_meta.get("prior_round_state")
    cr_snapshot = None

    if cr_id:
        cr_snapshot_result = await supabase.table("candidate_rounds") \
            .select("id, round_id, candidate_id, status, meeting_url, scheduled_at, interviewer_email") \
            .eq("id", cr_id) \
            .limit(1) \
            .execute_async()
        if cr_snapshot_result.data:
            cr_snapshot = cr_snapshot_result.data[0]

    round_rollback_ok = True
    if cr_id:
        if cr_was_created:
            cr_undo = await supabase.table("candidate_rounds") \
                .update({"status": "cancelled", "updated_at": datetime.now(timezone.utc).isoformat()}) \
                .eq("id", cr_id) \
                .in_("status", ["pending", "scheduled"]) \
                .execute_async()
            if not cr_undo.data:
                round_rollback_ok = False
        elif prior_round_state:
            restore_data = {"updated_at": datetime.now(timezone.utc).isoformat()}
            for field in ("status", "meeting_url", "scheduled_at", "interviewer_email"):
                if field in prior_round_state:
                    restore_data[field] = prior_round_state[field]
            cr_undo = await supabase.table("candidate_rounds") \
                .update(restore_data) \
                .eq("id", cr_id) \
                .in_("status", ["pending", "scheduled"]) \
                .execute_async()
            if not cr_undo.data:
                round_rollback_ok = False
            else:
                logger.info(f"Calendar Intelligence: undo restored prior round state for cr={cr_id}")
        else:
            cr_undo = await supabase.table("candidate_rounds") \
                .update({"status": "cancelled", "updated_at": datetime.now(timezone.utc).isoformat()}) \
                .eq("id", cr_id) \
                .in_("status", ["pending", "scheduled"]) \
                .execute_async()
            if not cr_undo.data:
                round_rollback_ok = False

    if not round_rollback_ok:
        await _update_slack_message(payload, [
            _build_context_header(detection, step_override="review"),
            {"type": "section", "block_id": "cal_intel_undo_failed_round",
             "text": {"type": "mrkdwn",
                      "text": ":x: Undo failed: the interview round has already progressed. Manage it from the dashboard."}},
            build_open_in_app_action_block(detection, "undo_failed_round"),
        ])
        return

    bot_result = await supabase.table("recall_bots") \
        .select("id, recall_bot_id, status") \
        .eq("detection_id", detection_id) \
        .execute_async()

    # Codex Round 5: split undo bot handling into two phases.
    #   Phase 1 — Remote ops: attempt cancel/delete on every bot, track
    #             per-bot success/failure WITHOUT touching the DB. Remote
    #             cancels are irreversible, so we must capture reality
    #             before mutating our state.
    #   Phase 2 — DB sync: apply DB mutations for every bot whose remote op
    #             succeeded so the DB reflects remote reality. Bots whose
    #             remote op failed are left UNCHANGED in the DB; the
    #             compensation path below restores the candidate_round so
    #             the detection is left in a consistent "undo failed" state
    #             that the user can retry or resolve from the dashboard.
    bot_cancel_failed = False
    bot_remote_ops: list[dict] = []  # [{bot, cancelled_remote, success, exception}]

    if bot_result.data:
        from app.services.recall_service import get_recall_service
        recall = get_recall_service()
        # Phase 1: remote ops only — no DB writes.
        for bot in bot_result.data:
            bot_status = bot.get("status")
            try:
                cancelled_remote = False
                if bot_status in ("in_call_recording", "in_call_not_recording"):
                    await recall.remove_bot_from_call(bot["recall_bot_id"])
                    cancelled_remote = True
                elif bot_status in ("created", "joining", "in_waiting_room"):
                    await recall.delete_bot(bot["recall_bot_id"])
                    cancelled_remote = True
                bot_remote_ops.append({
                    "bot": bot,
                    "cancelled_remote": cancelled_remote,
                    "success": True,
                    "exception": None,
                })
            except Exception as e:
                bot_cancel_failed = True
                bot_remote_ops.append({
                    "bot": bot,
                    "cancelled_remote": False,
                    "success": False,
                    "exception": e,
                })
                logger.error(
                    f"Calendar Intelligence: undo bot remote cancel failed "
                    f"for bot={bot.get('id')} recall_bot_id={bot.get('recall_bot_id')}: {e}"
                )

        # Phase 2: mirror remote reality in the DB — but only for bots whose
        # Phase 1 op completed successfully. Bots with remote failures stay
        # linked+active in the DB so operator retries see the true state.
        # Codex Round 3: mirror Recall cancellation in DB so
        # _link_bot_to_candidate_round cannot reuse stale/cancelled bots on
        # re-confirm. Two cases:
        #   (1) Active bot we just cancelled → set status="cancelled"
        #       (reflects remote reality).
        #   (2) Terminal bot (done/processing/call_ended) → unlink by
        #       clearing detection_id so the completed recording row stays
        #       intact but will not be rematched to a fresh re-confirm of
        #       this detection.
        for op in bot_remote_ops:
            if not op["success"]:
                continue
            bot = op["bot"]
            try:
                if op["cancelled_remote"]:
                    await supabase.table("recall_bots") \
                        .update({
                            "status": "cancelled",
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }) \
                        .eq("id", bot["id"]) \
                        .execute_async()
                else:
                    await supabase.table("recall_bots") \
                        .update({
                            "detection_id": None,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }) \
                        .eq("id", bot["id"]) \
                        .execute_async()
            except Exception as e:
                # DB sync failure after a successful remote op — this is a
                # worse state than a remote failure because our DB now lies
                # about remote reality. Signal to the compensation path so
                # the user sees "undo failed" and operators are alerted via
                # the error log. We do NOT retry here; subsequent undo
                # attempts will see the still-linked bot and try again.
                bot_cancel_failed = True
                logger.error(
                    f"Calendar Intelligence: undo DB sync failed after remote "
                    f"cancel for bot={bot.get('id')} — DB/remote drift: {e}"
                )

    if bot_cancel_failed:
        if cr_id:
            await supabase.table("candidate_rounds") \
                .update({
                    "status": "scheduled",
                    "meeting_url": detection.get("meeting_url"),
                    "scheduled_at": detection.get("event_start"),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }) \
                .eq("id", cr_id) \
                .in_("status", ["cancelled", "pending", "scheduled"]) \
                .execute_async()
            logger.info(f"Calendar Intelligence: undo compensated — restored cr={cr_id} after bot cancel failure")
        await _update_slack_message(payload, [
            _build_context_header(detection, step_override="review"),
            {"type": "section", "block_id": "cal_intel_undo_failed_bot",
             "text": {"type": "mrkdwn",
                      "text": ":x: Undo failed: could not cancel the recording bot. Please try again or contact support."}},
            build_open_in_app_action_block(detection, "undo_failed_bot"),
        ])
        return

    now = datetime.now(timezone.utc).isoformat()
    existing_signals = detection.get("detection_signals") or {}
    if not isinstance(existing_signals, dict):
        existing_signals = {}
    ui_state = existing_signals.get("_ui_state") or {}
    if not isinstance(ui_state, dict):
        ui_state = {}

    req_id = detection.get("matched_requisition_id") or ui_state.get("selected_requisition_id")
    role_title = ui_state.get("role_title", "")
    if req_id and not role_title:
        req_result = await supabase.table("requisitions") \
            .select("role_title") \
            .eq("id", req_id) \
            .is_("deleted_at", "null") \
            .limit(1) \
            .execute_async()
        if req_result.data:
            role_title = req_result.data[0].get("role_title", "")

    selected_round_id = None
    if cr_snapshot and cr_snapshot.get("round_id"):
        selected_round_id = str(cr_snapshot["round_id"])
    elif ui_state.get("selected_round_id"):
        selected_round_id = str(ui_state.get("selected_round_id"))

    round_data = None
    rounds_for_req = []
    if req_id:
        rounds_for_req = await _fetch_rounds_for_requisition(supabase, str(req_id))
        for rd in rounds_for_req:
            if selected_round_id and str(rd.get("id")) == selected_round_id:
                round_data = rd
                break

    if selected_round_id and not round_data:
        round_result = await supabase.table("rounds") \
            .select("id, name, duration_minutes, requisition_id") \
            .eq("id", selected_round_id) \
            .is_("deleted_at", "null") \
            .limit(1) \
            .execute_async()
        if round_result.data:
            round_data = round_result.data[0]
            if not req_id and round_data.get("requisition_id"):
                req_id = str(round_data["requisition_id"])
                rounds_for_req = await _fetch_rounds_for_requisition(supabase, str(req_id))

    new_status = "awaiting_confirm" if round_data else "awaiting_round"
    ui_state["current_step"] = "review" if round_data else "detected"
    ui_state["selected_requisition_id"] = str(req_id) if req_id else None
    ui_state["selected_round_id"] = str(round_data["id"]) if round_data else None
    ui_state["role_title"] = role_title or ""
    ui_state["round_candidates"] = _minimal_round_candidates(rounds_for_req) if rounds_for_req else []
    existing_signals["_ui_state"] = ui_state
    existing_signals.pop("_undo_metadata", None)
    context_detection = dict(detection)
    context_detection["detection_signals"] = existing_signals
    context_detection["detection_status"] = new_status
    existing_signals = merge_interaction_context(
        existing_signals,
        context_detection,
        role_title=role_title,
        round_name=(round_data.get("name", "Round") if round_data else ""),
        current_step=ui_state.get("current_step", ""),
    )

    undo_cas = await supabase.table("calendar_event_detections") \
        .update({
            "detection_status": new_status,
            "undo_expires_at": None,
            "detection_signals": existing_signals,
            "updated_at": now,
        }) \
        .eq("id", detection_id) \
        .eq("detection_status", "confirmed") \
        .execute_async()
    if not undo_cas.data:
        logger.warning(f"Calendar Intelligence: undo CAS failed for detection={detection_id} — status already changed")
        raise DetectionAlreadyProcessedError()

    notice_block = {
        "type": "section",
        "block_id": "cal_intel_undone",
        "text": {
            "type": "mrkdwn",
            "text": (
                ":leftwards_arrow_with_hook: Undone — interview unscheduled, bot cancelled.\n"
                "You can review and confirm setup again below."
            ),
        },
    }
    if round_data:
        blocks = _build_review_blocks_with_candidate_disambiguation(
            detection=detection,
            role_title=role_title,
            round_data=round_data,
            show_back_to_round=len(rounds_for_req) >= 1,
            ui_state=ui_state,
        )
        blocks.insert(1, notice_block)
        await _update_slack_message(payload, blocks)
    else:
        refreshed = dict(detection)
        refreshed["detection_signals"] = existing_signals
        blocks = await _build_detected_step_blocks(supabase, refreshed)
        blocks.insert(1, notice_block)
        await _update_slack_message(payload, blocks)

    logger.info(f"Calendar Intelligence: undone detection={detection_id}")


async def _build_confirmed_summary_blocks(
    detection: dict,
    supabase,
    extra_status_lines: list[str],
    *,
    include_send_prep: bool = False,
) -> list[dict]:
    cr_id = detection.get("matched_candidate_round_id")
    if not cr_id:
        blocks = [_build_context_header(detection, step_override="confirmed")]
        blocks.append({
            "type": "section",
            "block_id": "cal_intel_confirmed_status_fallback",
            "text": {"type": "mrkdwn", "text": "\n".join(extra_status_lines)},
        })
        blocks.append({
            "type": "actions",
            "block_id": "cal_intel_confirmed_status_fallback_actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Undo"},
                    "action_id": "cal_intel_undo",
                    "style": "danger",
                    "value": f'{{"detection_id": "{detection.get("id", "")}"}}',
                },
            ],
        })
        blocks.append(build_open_in_app_action_block(detection, "confirmed_fallback"))
        return blocks

    cr_result = await supabase.table("candidate_rounds") \
        .select("round_id, candidate_id, interviewer_email") \
        .eq("id", cr_id) \
        .limit(1) \
        .execute_async()
    if not cr_result.data:
        return [
            _build_context_header(detection, step_override="confirmed"),
            {
                "type": "section",
                "block_id": "cal_intel_confirmed_status_no_round",
                "text": {"type": "mrkdwn", "text": "\n".join(extra_status_lines)},
            },
            {
                "type": "actions",
                "block_id": "cal_intel_confirmed_status_no_round_actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Undo"},
                        "action_id": "cal_intel_undo",
                        "style": "danger",
                        "value": f'{{"detection_id": "{detection.get("id", "")}"}}',
                    },
                ],
            },
            build_open_in_app_action_block(detection, "confirmed_no_round"),
        ]
    cr = cr_result.data[0]

    round_name = "Round"
    round_result = await supabase.table("rounds") \
        .select("name") \
        .eq("id", cr["round_id"]) \
        .limit(1) \
        .execute_async()
    if round_result.data:
        round_name = round_result.data[0].get("name", "Round")

    candidate_name = ""
    candidate_email = ""
    candidate_result = await supabase.table("candidates") \
        .select("name, email") \
        .eq("id", cr["candidate_id"]) \
        .limit(1) \
        .execute_async()
    if candidate_result.data:
        candidate_name = candidate_result.data[0].get("name", "") or ""
        candidate_email = candidate_result.data[0].get("email", "") or ""
    if not candidate_name or not candidate_email:
        external = detection.get("external_attendees") or []
        if external:
            candidate_email = candidate_email or external[0].get("email", "")
            if not candidate_name and candidate_email:
                from app.services.calendar_intelligence_service import resolve_candidate_name
                candidate_name = resolve_candidate_name(detection, candidate_email)
            candidate_name = candidate_name or external[0].get("display_name", "")

    interviewer_email = cr.get("interviewer_email") or ""
    if not interviewer_email:
        internal = detection.get("internal_attendees") or []
        for attendee in internal:
            if attendee.get("email") and not attendee.get("self"):
                interviewer_email = attendee["email"]
                break
        if not interviewer_email:
            for attendee in internal:
                if attendee.get("email") and attendee.get("self"):
                    interviewer_email = attendee["email"]
                    break

    role_title = ""
    req_id = detection.get("matched_requisition_id")
    if req_id:
        req_result = await supabase.table("requisitions") \
            .select("role_title") \
            .eq("id", req_id) \
            .is_("deleted_at", "null") \
            .limit(1) \
            .execute_async()
        if req_result.data:
            role_title = req_result.data[0].get("role_title") or ""

    return build_confirmation_blocks(
        detection,
        candidate_name or candidate_email or "Candidate",
        round_name,
        role_title,
        candidate_email=candidate_email,
        interviewer_email=interviewer_email,
        include_actions=True,
        include_send_prep=include_send_prep,
        include_undo=True,
        extra_status_lines=extra_status_lines,
    )


async def _send_prep(detection_id: str, payload: dict):
    detection = await _get_detection(detection_id)
    if detection["detection_status"] != "confirmed":
        raise DetectionAlreadyProcessedError()

    supabase = get_supabase_admin_client()
    cr_id = detection.get("matched_candidate_round_id")
    if not cr_id:
        await _update_slack_message(payload, [
            _build_context_header(detection, step_override="confirmed"),
            {"type": "section", "block_id": "cal_intel_prep_error_no_round",
             "text": {"type": "mrkdwn", "text": ":x: No round linked to send prep."}},
            {
                "type": "actions",
                "block_id": "cal_intel_prep_error_no_round_actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Undo"},
                        "action_id": "cal_intel_undo",
                        "style": "danger",
                        "value": f'{{"detection_id": "{detection_id}"}}',
                    },
                ],
            },
            build_open_in_app_action_block(detection, "prep_no_round"),
        ])
        return

    cr_result = await supabase.table("candidate_rounds") \
        .select("round_id, candidate_id, meeting_url, scheduled_at, scheduling_timezone, interviewer_email") \
        .eq("id", cr_id) \
        .execute_async()
    if not cr_result.data:
        return

    cr = cr_result.data[0]
    round_result = await supabase.table("rounds") \
        .select("name, guidelines, default_interviewer_emails") \
        .eq("id", cr["round_id"]) \
        .execute_async()
    if not round_result.data:
        return

    round_info = round_result.data[0]
    interviewer_emails = []

    # Highest-priority: interviewer resolved and stored at confirm time.
    if cr.get("interviewer_email"):
        interviewer_emails.append(str(cr["interviewer_email"]).strip())

    default_interviewer_emails = round_info.get("default_interviewer_emails") or []
    if default_interviewer_emails:
        current_internal = {
            a.get("email", "").lower()
            for a in (detection.get("internal_attendees") or [])
            if a.get("email")
        }
        if current_internal:
            default_interviewer_emails = [
                e for e in default_interviewer_emails if isinstance(e, str) and e.lower() in current_internal
            ]
        interviewer_emails.extend(default_interviewer_emails)

    if not interviewer_emails:
        recruiter_email = ""
        try:
            user_conn = await supabase.table("user_connections") \
                .select("provider_email") \
                .eq("profile_id", detection["profile_id"]) \
                .eq("provider", "google_calendar") \
                .eq("is_active", True) \
                .limit(1) \
                .execute_async()
            recruiter_email = user_conn.data[0]["provider_email"] if user_conn.data else ""
        except Exception:
            recruiter_email = ""

        from app.services.calendar_intelligence_service import resolve_interviewer_email
        resolved = resolve_interviewer_email(
            detection.get("internal_attendees", []),
            round_info,
            recruiter_email,
        )
        if resolved:
            interviewer_emails.append(resolved)

    if not interviewer_emails:
        internal = detection.get("internal_attendees") or []
        interviewer_emails = [a.get("email") for a in internal if a.get("email") and not a.get("self")]
        if not interviewer_emails:
            interviewer_emails = [a.get("email") for a in internal if a.get("email") and a.get("self")]

    external_emails = {a.get("email", "").lower() for a in (detection.get("external_attendees") or []) if a.get("email")}
    internal_domains = {a.get("email", "").split("@")[-1].lower() for a in (detection.get("internal_attendees") or []) if a.get("email") and "@" in a.get("email", "")}
    interviewer_emails = [
        e for e in interviewer_emails
        if e
        and e.lower() not in external_emails
        and (not internal_domains or ("@" in e and e.split("@")[-1].lower() in internal_domains))
    ]
    interviewer_emails = list(dict.fromkeys(e.lower() for e in interviewer_emails if isinstance(e, str) and "@" in e))

    cand_result = await supabase.table("candidates") \
        .select("name, email") \
        .eq("id", cr["candidate_id"]) \
        .execute_async()
    cand = cand_result.data[0] if cand_result.data else {}

    role_title = ""
    req_id = detection.get("matched_requisition_id")
    if req_id:
        req_result = await supabase.table("requisitions") \
            .select("role_title") \
            .eq("id", req_id) \
            .is_("deleted_at", "null") \
            .limit(1) \
            .execute_async()
        if req_result.data:
            role_title = req_result.data[0].get("role_title") or ""

    if not interviewer_emails:
        summary_blocks = build_confirmation_blocks(
            detection,
            cand.get("name") or cand.get("email") or "Candidate",
            round_info.get("name", "Round"),
            role_title,
            candidate_email=cand.get("email", ""),
            interviewer_email="",
            include_actions=True,
            include_send_prep=False,
            include_undo=True,
            extra_status_lines=[":x: No interviewer email found. Copy guidelines manually."],
        )
        await _update_slack_message(payload, summary_blocks)
        return

    guidelines = round_info.get("guidelines") or []
    guidelines_text = ""
    for g in guidelines:
        guidelines_text += f"*{g.get('title', '')}*\n{g.get('description', '')}\n\n"

    prep_blocks = [
        {
            "type": "section",
            "block_id": "cal_intel_prep_header",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":clipboard: *Interview Prep — {round_info.get('name', 'Round')}*\n"
                    f":bust_in_silhouette: Candidate: {cand.get('name', 'Unknown')} ({cand.get('email', '')})\n"
                    f":calendar: {detection.get('event_title', 'Meeting')}"
                ),
            },
        },
    ]
    if guidelines_text.strip():
        prep_blocks.append({
            "type": "section",
            "block_id": "cal_intel_prep_guidelines",
            "text": {"type": "mrkdwn", "text": f"*Guidelines:*\n{guidelines_text.strip()[:2900]}"},
        })

    service = get_slack_service()
    sent_to = []
    failed = []

    org_id = detection.get("organization_id")
    team_data = payload.get("team", {})
    team_id = team_data.get("id") if isinstance(team_data, dict) else team_data

    for email in interviewer_emails:
        slack_user_id = await service.find_slack_user_by_profile_email(
            email, organization_id=org_id, slack_team_id=team_id
        )
        if slack_user_id:
            try:
                bot_token = await service.get_bot_token_for_team(team_id)
                await service.send_dm(
                    bot_token=bot_token,
                    slack_user_id=slack_user_id,
                    text=f"Interview prep for {cand.get('name', 'candidate')}",
                    blocks=prep_blocks,
                    team_id=team_id,
                )
                sent_to.append(email)
            except Exception as e:
                logger.error(f"Calendar Intelligence: send_prep DM failed for {email}: {e}")
                failed.append(email)
        else:
            failed.append(email)

    emailed_to = []
    if failed:
        from app.services.email.service import get_email_service
        email_svc = get_email_service()
        guidelines_html = build_guidelines_html(round_info.get("guidelines") or [])
        detection_signals = detection.get("detection_signals") or {}
        if not isinstance(detection_signals, dict):
            detection_signals = {}
        tz_hint = str(cr.get("scheduling_timezone") or "").strip() or str(detection_signals.get("_display_timezone") or "")
        scheduled_at_display = format_event_time_for_email(cr.get("scheduled_at"), tz_hint)
        for email in failed:
            try:
                interviewer_name = email.split("@")[0].replace(".", " ").replace("_", " ").title()
                result = await email_svc.send_templated_email(
                    to_email=email,
                    to_name=interviewer_name,
                    subject=f"Interview Prep — {round_info.get('name', 'Round')} — {cand.get('name', 'Candidate')}",
                    template_name="prep_guidelines.html",
                    context={
                        "interviewer_name": interviewer_name,
                        "candidate_name": cand.get("name", "Unknown"),
                        "candidate_email": cand.get("email", ""),
                        "round_name": round_info.get("name", "Round"),
                        "scheduled_at": scheduled_at_display,
                        "event_title": detection.get("event_title", ""),
                        "guidelines_html": guidelines_html,
                    },
                )
                if result.success:
                    emailed_to.append(email)
            except Exception as e:
                logger.error(f"Calendar Intelligence: prep email failed for {email}: {e}")

    parts = []
    if sent_to:
        parts.append(f":white_check_mark: Prep sent via Slack to: {', '.join(sent_to)}")
    if emailed_to:
        parts.append(f":email: Prep emailed to: {', '.join(emailed_to)} (not on OpenRecruiting Slack)")
    truly_failed = [e for e in failed if e not in emailed_to]
    if truly_failed:
        parts.append(f":warning: Could not reach: {', '.join(truly_failed)}")

    if not parts:
        parts = [":x: No interviewers could be reached via Slack or email."]

    summary_blocks = build_confirmation_blocks(
        detection,
        cand.get("name") or cand.get("email") or "Candidate",
        round_info.get("name", "Round"),
        role_title,
        candidate_email=cand.get("email", ""),
        interviewer_email=(interviewer_emails[0] if interviewer_emails else ""),
        include_actions=True,
        include_send_prep=False,
        include_undo=True,
        extra_status_lines=parts,
    )
    await _update_slack_message(payload, summary_blocks)


async def _handle_reschedule_update(detection_id: str, new_start: str, payload: dict):
    if not new_start:
        return

    detection = await _get_detection(detection_id)
    if detection["detection_status"] != "confirmed":
        raise DetectionAlreadyProcessedError()
    cr_id = detection.get("matched_candidate_round_id")

    supabase = get_supabase_admin_client()

    if cr_id:
        await supabase.table("candidate_rounds") \
            .update({
                "scheduled_at": new_start,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }) \
            .eq("id", cr_id) \
            .in_("status", ["pending", "scheduled"]) \
            .execute_async()

    bot_result = await supabase.table("recall_bots") \
        .select("id, recall_bot_id, status") \
        .eq("detection_id", detection_id) \
        .execute_async()

    bot_update_failed = False
    if bot_result.data and cr_id:
        from app.services.recall_service import get_recall_service, schedule_or_replace_recall_bot
        recall = get_recall_service()
        parsed_time = datetime.fromisoformat(new_start)
        for bot in bot_result.data:
            try:
                if bot.get("status") in BOT_SPINUP_STATUSES:
                    await recall.delete_bot(bot["recall_bot_id"])
                    await supabase.table("recall_bots") \
                        .update({"status": "cancelled", "updated_at": datetime.now(timezone.utc).isoformat()}) \
                        .eq("id", bot["id"]) \
                        .execute_async()
            except Exception as e:
                logger.error(f"Calendar Intelligence: cancel old bot failed: {e}")
                bot_update_failed = True
        if not bot_update_failed:
            try:
                meeting_url = detection.get("meeting_url", "")
                external = detection.get("external_attendees") or []
                cand_name = external[0].get("display_name", "Candidate") if external else "Candidate"
                await schedule_or_replace_recall_bot(
                    candidate_round_id=cr_id,
                    meeting_url=meeting_url,
                    scheduled_at=parsed_time,
                    candidate_name=cand_name,
                )
                new_bot = await supabase.table("recall_bots") \
                    .select("id") \
                    .eq("candidate_round_id", cr_id) \
                    .in_("status", ["created", "joining"]) \
                    .order("created_at", desc=True) \
                    .limit(1) \
                    .execute_async()
                if new_bot.data:
                    await supabase.table("recall_bots") \
                        .update({"detection_id": detection_id, "source": "calendar_intelligence"}) \
                        .eq("id", new_bot.data[0]["id"]) \
                        .execute_async()
            except Exception as e:
                logger.error(f"Calendar Intelligence: deploy rescheduled bot failed: {e}")
                bot_update_failed = True

    if bot_update_failed:
        summary_blocks = await _build_confirmed_summary_blocks(
            detection,
            supabase,
            [":x: Interview time updated but bot reschedule failed. The recording bot may need manual setup."],
            include_send_prep=False,
        )
        await _update_slack_message(payload, summary_blocks)
    else:
        summary_blocks = await _build_confirmed_summary_blocks(
            detection,
            supabase,
            [":white_check_mark: Interview time updated in OpenRecruiting."],
            include_send_prep=False,
        )
        await _update_slack_message(payload, summary_blocks)


# Codex Round 3: terminal states (call_ended/processing/done) and failure
# states must NOT be reattachable — they represent a bot that has already
# finished its job and cannot be used for a fresh candidate_round. Only
# pre-call and in-call statuses are considered live for reuse.
def _is_untracked_capture_detection(detection: dict) -> bool:
    signals = detection.get("detection_signals") or {}
    return isinstance(signals, dict) and bool(signals.get("untracked_capture"))


def _event_start_has_passed(detection: dict) -> bool:
    event_start = detection.get("event_start")
    if not isinstance(event_start, str) or not event_start.strip():
        return False

    text = event_start.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        scheduled_at = datetime.fromisoformat(text)
    except Exception:
        return False

    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)

    return scheduled_at <= datetime.now(timezone.utc)


async def _cancel_detection_bots_for_replacement(detection_id: str, supabase) -> bool:
    rows = await supabase.table("recall_bots") \
        .select("id, recall_bot_id, status") \
        .eq("detection_id", detection_id) \
        .execute_async()
    bots = rows.data or []
    if not bots:
        return True

    from app.services.recall_service import get_recall_service

    recall = get_recall_service()
    all_ok = True
    try:
        for bot in bots:
            bot_status = str(bot.get("status") or "")
            bot_id = str(bot.get("id") or "")
            recall_bot_id = str(bot.get("recall_bot_id") or "")
            cancelled_remote = False
            remote_attempted = False

            try:
                if bot_status in ("in_call_recording", "in_call_not_recording"):
                    remote_attempted = True
                    cancelled_remote = await recall.remove_bot_from_call(recall_bot_id)
                    if not cancelled_remote:
                        all_ok = False
                elif bot_status in ("created", "joining", "in_waiting_room"):
                    remote_attempted = True
                    cancelled_remote = await recall.delete_bot(recall_bot_id)
                    if not cancelled_remote:
                        all_ok = False
                else:
                    cancelled_remote = False
            except Exception as exc:
                all_ok = False
                logger.warning(
                    f"Calendar Intelligence: failed replacing bot for detection={detection_id} "
                    f"bot={bot_id} recall_bot_id={recall_bot_id}: {exc}"
                )
                continue

            if remote_attempted and not cancelled_remote:
                # Keep DB row untouched when remote cancellation failed.
                continue

            now = datetime.now(timezone.utc).isoformat()
            try:
                if cancelled_remote:
                    await supabase.table("recall_bots") \
                        .update({"status": "cancelled", "updated_at": now}) \
                        .eq("id", bot_id) \
                        .execute_async()
                else:
                    await supabase.table("recall_bots") \
                        .update({"detection_id": None, "updated_at": now}) \
                        .eq("id", bot_id) \
                        .execute_async()
            except Exception as exc:
                all_ok = False
                logger.warning(
                    f"Calendar Intelligence: failed syncing bot replacement state for "
                    f"detection={detection_id} bot={bot_id}: {exc}"
                )
    finally:
        try:
            await recall.close()
        except Exception:
            pass
    return all_ok


async def _deploy_fresh_detection_bot(
    detection: dict,
    candidate_round_id: str,
    supabase,
) -> bool:
    from app.services.recall_service import schedule_or_replace_recall_bot

    meeting_url = detection.get("meeting_url")
    event_start = detection.get("event_start")
    external = detection.get("external_attendees") or []
    candidate_name = external[0].get("display_name", "Candidate") if external else "Candidate"
    if not meeting_url or not event_start:
        return False

    scheduled_at = datetime.fromisoformat(event_start) if isinstance(event_start, str) else event_start
    await schedule_or_replace_recall_bot(
        candidate_round_id=candidate_round_id,
        meeting_url=meeting_url,
        scheduled_at=scheduled_at,
        candidate_name=candidate_name,
    )
    fresh_bot = await supabase.table("recall_bots") \
        .select("id") \
        .eq("candidate_round_id", candidate_round_id) \
        .in_("status", ["created", "joining", "in_waiting_room"]) \
        .order("created_at", desc=True) \
        .limit(1) \
        .execute_async()
    if not fresh_bot.data:
        logger.error(
            "Calendar Intelligence: replacement bot not found after deploy "
            f"for detection={detection.get('id')}"
        )
        return False

    await supabase.table("recall_bots") \
        .update(
            {
                "detection_id": str(detection.get("id") or ""),
                "source": "calendar_intelligence",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ) \
        .eq("id", fresh_bot.data[0]["id"]) \
        .execute_async()
    return True


async def _replace_untracked_detection_bot(
    detection: dict,
    candidate_round_id: str,
    supabase,
) -> bool:
    detection_id = str(detection.get("id") or "")
    if not detection_id:
        return False
    cancelled_ok = await _cancel_detection_bots_for_replacement(detection_id, supabase)
    if not cancelled_ok:
        return False
    return await _deploy_fresh_detection_bot(detection, candidate_round_id, supabase)


async def _link_detection_bot_for_confirm(
    detection: dict,
    candidate_round_id: str,
    supabase,
) -> bool:
    detection_id = str(detection.get("id") or "")
    if _is_untracked_capture_detection(detection):
        return await _replace_untracked_detection_bot(detection, candidate_round_id, supabase)
    return await _link_bot_to_candidate_round(detection_id, candidate_round_id, supabase)


async def _link_bot_to_candidate_round(detection_id: str, candidate_round_id: str, supabase) -> bool:
    """Returns True if a bot is successfully linked, False otherwise."""
    bot_result = await supabase.table("recall_bots") \
        .select("id, recall_bot_id, status, recording_url, transcript_url, transcript_ready") \
        .eq("detection_id", detection_id) \
        .execute_async()

    active_bots = [b for b in (bot_result.data or []) if b.get("status") in ATTACHABLE_BOT_STATUSES]

    if not active_bots:
        from app.services.recall_service import schedule_or_replace_recall_bot

        detection = await _get_detection(detection_id)
        meeting_url = detection.get("meeting_url")
        event_start = detection.get("event_start")
        external = detection.get("external_attendees") or []
        candidate_name = external[0].get("display_name", "Candidate") if external else "Candidate"

        if meeting_url and event_start:
            scheduled_at = datetime.fromisoformat(event_start) if isinstance(event_start, str) else event_start
            await schedule_or_replace_recall_bot(
                candidate_round_id=candidate_round_id,
                meeting_url=meeting_url,
                scheduled_at=scheduled_at,
                candidate_name=candidate_name,
            )
            fallback_bot = await supabase.table("recall_bots") \
                .select("id, status") \
                .eq("candidate_round_id", candidate_round_id) \
                .in_("status", ["created", "joining", "in_waiting_room"]) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute_async()
            if fallback_bot.data:
                await supabase.table("recall_bots") \
                    .update({"detection_id": detection_id, "source": "calendar_intelligence"}) \
                    .eq("id", fallback_bot.data[0]["id"]) \
                    .execute_async()
                return True
            logger.error(f"Calendar Intelligence: fallback bot not found after deploy for detection={detection_id}")
            return False
        return False

    bot = active_bots[0]
    await supabase.table("recall_bots") \
        .update({"candidate_round_id": candidate_round_id}) \
        .eq("id", bot["id"]) \
        .execute_async()

    if bot.get("transcript_ready") and bot.get("transcript_url"):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(bot["transcript_url"])
                if resp.status_code == 200:
                    transcript_data = resp.json()
                    await supabase.table("transcripts").upsert({
                        "candidate_round_id": candidate_round_id,
                        "segments": transcript_data,
                        "raw_transcript_url": bot["transcript_url"],
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                    }, on_conflict="candidate_round_id").execute_async()

                    from app.services.feedback_job_service import get_feedback_job_service
                    feedback_service = get_feedback_job_service()
                    await feedback_service.trigger_feedback_processing(candidate_round_id)
                    logger.info(f"Calendar Intelligence: transcript linked + feedback triggered for cr={candidate_round_id}")
        except Exception as e:
            logger.error(f"Calendar Intelligence: transcript link failed: {e}")

    return True


async def _update_slack_message(payload: dict, blocks: list[dict]):
    response_url = payload.get("response_url")
    if response_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                text = "Calendar Intelligence update"
                resp = await client.post(response_url, json={
                    "replace_original": True,
                    "text": text,
                    "blocks": blocks,
                })
                if resp.is_success:
                    logger.info(f"Calendar Intelligence: Slack response_url update status={resp.status_code}")
                    return
                logger.warning(f"Calendar Intelligence: response_url non-2xx status={resp.status_code} body={resp.text[:200]}, falling back to channel update")
        except Exception as e:
            logger.warning(f"Calendar Intelligence: response_url update failed: {e}, falling back to channel update")

    channel = payload.get("channel", {})
    channel_id = channel.get("id") if isinstance(channel, dict) else channel
    message_ts = payload.get("message", {}).get("ts")
    team_data = payload.get("team", {})
    team_id = team_data.get("id") if isinstance(team_data, dict) else team_data

    if channel_id and message_ts and team_id:
        service = get_slack_service()
        try:
            bot_token = await service.get_bot_token_for_team(team_id)
            await service.update_message(
                bot_token=bot_token,
                channel=channel_id,
                ts=message_ts,
                text="Calendar Intelligence update",
                blocks=blocks,
                team_id=team_id,
            )
        except Exception as e:
            logger.error(f"Calendar Intelligence: Slack message update failed: {e}")
