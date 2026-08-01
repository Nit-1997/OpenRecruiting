import asyncio
import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Literal
from app.config import get_settings
from app.logging_config import get_logger
from app.services.supabase import get_supabase_admin_client
from app.services.recall_calendar_service import get_recall_calendar_service
from app.services.calendar_intelligence_service import (
    analyze_event,
    llm_classify_and_extract,
    resolve_organizer,
    resolve_role_matches,
    transition_detection_status,
    build_detection_blocks,
    build_no_req_blocks,
    build_untracked_captured_blocks,
    build_reminder_blocks,
    build_reschedule_blocks,
    build_guidelines_html,
    format_event_time_for_email,
    merge_interaction_context,
)
from app.services.untracked_capture_service import (
    capture_untracked_interview,
    materialize_untracked_capture,
    is_untracked_capture_enabled,
)

logger = get_logger(__name__)

# Codex Round 7: explicit processing outcomes.
#   - "processed": the event was fully handled (detection inserted/updated,
#     notification sent, intentional no-op under existing detection, etc.)
#   - "drop": the event was permanently skipped for a reason that will not
#     change on retry (past event, not an interview, malformed, blocked
#     attendee domain, etc.). Safe to remove from the DLQ.
#   - "defer": processing could not complete for a reason that MIGHT change
#     on retry (missing user_lookup mapping, broken org_domain, insert
#     returned empty data). Must NOT be removed from the DLQ — the event is
#     kept for the next drain with incremented retry/backoff.
# Anything other than "defer" is treated as removable so untyped legacy
# callers (including unit tests that mock `_process_single_event` via
# AsyncMock and implicitly return MagicMock) remain backwards compatible.
ProcessingOutcome = Literal["processed", "defer", "drop"]

POLL_LOCK_STALE_SECONDS = 300
MAX_EVENT_RETRIES = 3
# Hard cap on how many open requisitions a single event can be matched against.
# This prevents unbounded fan-out in the hot event path for large tenants and
# keeps subsequent rounds/candidates queries sized predictably.
MAX_REQS_PER_EVENT = 100
# Maximum number of DLQ entries we remember. Bounded to prevent unbounded
# memory/DB growth on a misbehaving feed.
_DEAD_LETTER_MAX = 1024
# After this many exponential-backoff retries, an entry enters "exhausted"
# state: normal backoff retries stop, but the entry is still auto-replayed
# at a fixed long interval (see `_DEAD_LETTER_EXHAUSTED_RETRY_SECONDS`) so
# recovery is automatic once the underlying issue is fixed — the operator
# does NOT need to manually clear the DLQ for events to start flowing again.
# Codex Round 8: previous behavior hard-skipped these entries forever.
_DEAD_LETTER_MAX_RETRIES = 8
# How often to re-probe an exhausted DLQ entry. At 1 hour, a fix landed at
# any point during the day recovers within an hour on average. The DLQ
# overall is TTL-bounded (`_DEAD_LETTER_TTL_SECONDS` = 7 days) so a stuck
# entry will eventually expire even if the prerequisite never recovers.
_DEAD_LETTER_EXHAUSTED_RETRY_SECONDS = 3600  # 1 hour
# Permanent expiry — we drop DLQ entries this old even if retries are exhausted.
# Bounds how long a stuck entry stays in state at all.
_DEAD_LETTER_TTL_SECONDS = 7 * 24 * 3600
# Initial backoff after first dead-letter. Doubles each retry, capped.
_DEAD_LETTER_BACKOFF_INITIAL_SECONDS = 600  # 10 min
_DEAD_LETTER_BACKOFF_MAX_SECONDS = 6 * 3600  # 6 hours
# Supabase state key used to persist DLQ entries durably. Survives worker
# restarts and makes the current DLQ inspectable from SQL for alerting and
# replay. Value is a JSON array of entry dicts (see _DLQEntry shape below).
_DEAD_LETTER_STATE_KEY = "dead_letter_records"
_WEBHOOK_SYNC_HINT_STATE_KEY = "webhook_sync_hint_at"  # legacy global key
_WEBHOOK_SYNC_HINT_STATE_KEY_PREFIX = "webhook_sync_hint_at:"
_WEBHOOK_SYNC_PENDING_STATE_KEY_PREFIX = "webhook_sync_pending:"

_event_fail_counts: dict[str, int] = {}
# DLQ is now a replay queue keyed by composite `{event_id}:{content_signature}`.
# Each entry stores the full event snapshot so the worker can re-attempt
# processing WITHOUT re-fetching from Recall (incremental polling does NOT
# refetch unchanged events, so we can't rely on the upstream stream to
# redeliver). Each poll drains entries whose next_retry_at has elapsed. This
# lets `last_poll_at` advance safely because dead-lettered work is durably
# owned here, not implicitly deferred to the cursor.
#
# Entry shape:
#   {
#     "event": {...},              # full event dict for replay
#     "reason": "...",
#     "first_dead_lettered_at": 1712700000.0,
#     "retry_count": 0,
#     "next_retry_at": 1712700600.0,
#   }
_dead_letter_entries: dict[str, dict] = {}
_dead_letter_hydrated = False
# Light coalescing floor for non-critical additive update alerts (title/time/
# attendee churn). Cancellation and meeting-link changes bypass this.
CHANGE_NOTIFY_COALESCE_SECONDS = 300
# Webhook-driven sync requests can arrive out of order or slightly delayed.
# Rewind the hinted timestamp by a small safety window to avoid misses.
WEBHOOK_SYNC_SAFETY_WINDOW_SECONDS = 180
# Hard cap on how far webhook hints can backfill relative to last_poll.
WEBHOOK_SYNC_MAX_REWIND_SECONDS = 3600
# Optimistic-CAS retries for persisting earliest pending webhook hint.
WEBHOOK_SYNC_HINT_MERGE_MAX_RETRIES = 8
# Cache Recall calendar status probes so we don't call /calendars/{id} for
# every single event in a hot poll batch.
_CALENDAR_STATUS_CACHE_TTL_SECONDS = 300
_calendar_status_cache: dict[str, tuple[str, float]] = {}
_DETECTION_BOT_ATTACHABLE_STATUSES = [
    "created",
    "joining",
    "in_waiting_room",
    "in_call_not_recording",
    "in_call_recording",
]


def _stable_platform_id(event: dict) -> str:
    """Canonical provider event identity normalized by Recall."""
    raw = event.get("raw") or {}
    return str(event.get("platform_id") or raw.get("id") or "").strip()


def _stable_ical_uid(event: dict) -> str:
    """RFC-5545 stable UID (cross-reconnect / cross-provider identity)."""
    raw = event.get("raw") or {}
    return str(event.get("ical_uid") or raw.get("iCalUID") or raw.get("icalUID") or "").strip()


def _stable_instance_key(event: dict) -> str:
    """Stable recurring-instance identity (series + original start) when available."""
    raw = event.get("raw") or {}
    series_id = str(
        raw.get("recurringEventId")
        or raw.get("recurring_event_id")
        or raw.get("seriesMasterId")
        or raw.get("series_master_id")
        or ""
    ).strip()
    original_start = raw.get("originalStartTime") or raw.get("original_start_time") or {}
    if isinstance(original_start, dict):
        original_start_val = str(
            original_start.get("dateTime")
            or original_start.get("date")
            or original_start.get("date_time")
            or ""
        ).strip()
    else:
        original_start_val = str(original_start or "").strip()
    if not original_start_val:
        original_start_val = str(raw.get("originalStart") or raw.get("original_start") or "").strip()
    if series_id and original_start_val:
        return f"{series_id}@{original_start_val}"
    return ""


def _parse_scheduled_at(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


async def _schedule_detection_voice_bot(
    *,
    supabase,
    detection_id: str,
    meeting_url: str,
    event_start,
    candidate_name: str,
) -> str | None:
    if not detection_id or not meeting_url:
        return None

    existing = await supabase.table("recall_bots") \
        .select("id, recall_bot_id, status, voice_session_token") \
        .eq("detection_id", detection_id) \
        .in_("status", _DETECTION_BOT_ATTACHABLE_STATUSES) \
        .order("created_at", desc=True) \
        .limit(1) \
        .execute_async()
    if existing.data:
        existing_row = existing.data[0]
        existing_recall_bot_id = str(existing_row.get("recall_bot_id") or "")
        if existing_recall_bot_id:
            if not existing_row.get("voice_session_token"):
                logger.warning(
                    "Calendar Intelligence: detection-level bot exists without voice token "
                    f"detection={detection_id} bot={existing_recall_bot_id}"
                )
            return existing_recall_bot_id

    scheduled_at = _parse_scheduled_at(event_start)
    if not scheduled_at:
        logger.warning(
            "Calendar Intelligence: cannot schedule detection voice bot due to invalid event_start "
            f"detection={detection_id} event_start={event_start}"
        )
        return None

    from app.services.recall_service import get_recall_service

    recall = get_recall_service()
    try:
        bot_response = await recall.schedule_bot(
            meeting_url=meeting_url,
            scheduled_at=scheduled_at,
            candidate_name=candidate_name or "Candidate",
            # Required by helper signature but not used in Recall payload.
            candidate_round_id=detection_id,
        )
        recall_bot_id = str(bot_response.get("id") or "")
        if not recall_bot_id:
            logger.error(
                "Calendar Intelligence: recall schedule returned missing bot id "
                f"detection={detection_id}"
            )
            return None

        recall_bot_insert = {
            "recall_bot_id": recall_bot_id,
            "meeting_url": meeting_url,
            "scheduled_at": scheduled_at.isoformat(),
            "status": "created",
            "detection_id": detection_id,
            "source": "calendar_intelligence",
            "bot_name": bot_response.get("bot_name", "OpenRecruiting"),
            "candidate_name": candidate_name or "Candidate",
        }
        voice_token = bot_response.get("_voice_session_token")
        if voice_token:
            recall_bot_insert["voice_session_token"] = voice_token
        else:
            logger.warning(
                "Calendar Intelligence: detection bot scheduled without voice token "
                f"detection={detection_id} bot={recall_bot_id}"
            )

        await supabase.table("recall_bots").insert(recall_bot_insert).execute_async()
        return recall_bot_id
    except Exception as e:
        logger.error(
            f"Calendar Intelligence: detection voice bot scheduling failed detection={detection_id}: {e}",
            exc_info=True,
        )
        return None
    finally:
        try:
            await recall.close()
        except Exception as close_err:
            logger.warning(f"Calendar Intelligence: recall client close failed: {close_err}")


async def _rollback_detection_voice_bot(supabase, recall_bot_id: str) -> None:
    recall_bot_id = str(recall_bot_id or "")
    if not recall_bot_id:
        return

    from app.services.recall_service import get_recall_service

    recall = get_recall_service()
    cancelled_remote = False
    try:
        cancelled_remote = await recall.delete_bot(recall_bot_id)
        if not cancelled_remote:
            cancelled_remote = await recall.remove_bot_from_call(recall_bot_id)
            if cancelled_remote:
                cancelled_remote = await recall.delete_bot(recall_bot_id)
    except Exception as e:
        logger.error(
            f"Calendar Intelligence: detection bot rollback failed bot={recall_bot_id}: {e}",
            exc_info=True,
        )
    finally:
        try:
            await recall.close()
        except Exception as close_err:
            logger.warning(f"Calendar Intelligence: recall client close failed: {close_err}")

    if cancelled_remote:
        await supabase.table("recall_bots") \
            .update({"status": "cancelled", "updated_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("recall_bot_id", recall_bot_id) \
            .execute_async()
    else:
        logger.warning(
            "Calendar Intelligence: could not cancel detection bot remotely "
            f"bot={recall_bot_id}; leaving DB status unchanged"
        )


def _canonical_event_identity(event: dict) -> tuple[str, str, str, str]:
    """Canonical identity tuple used for idempotent dedupe.

    Returns:
      (source, base_key, instance_key, compound_key)
    """
    ical_uid = _stable_ical_uid(event)
    platform_id = _stable_platform_id(event)
    recall_event_id = str(event.get("id") or "").strip()
    instance_key = _stable_instance_key(event)

    if ical_uid:
        source = "ical_uid"
        base_key = ical_uid
    elif platform_id:
        source = "platform_id"
        base_key = platform_id
    else:
        source = "recall_event_id"
        base_key = recall_event_id or "unknown"

    compound = f"{source}:{base_key}"
    if instance_key:
        compound = f"{compound}#{instance_key}"
    return source, base_key, instance_key, compound


def _extract_meeting_url_for_signature(event: dict) -> str:
    raw = event.get("raw") or {}
    conference = raw.get("conferenceData") or {}
    for entry in (conference.get("entryPoints") or []):
        if isinstance(entry, dict) and entry.get("entryPointType") == "video":
            uri = str(entry.get("uri") or "").strip()
            if uri:
                return uri
    for key in ("hangoutLink", "conferenceLink"):
        val = str(raw.get(key) or "").strip()
        if val:
            return val
    return ""


def _notification_signature(event: dict, org_domain: str = "") -> str:
    """Stable signature for user-facing change notifications.

    Unlike `_event_signature`, this intentionally excludes provider version
    counters so harmless `updated_at` bumps do not generate Slack noise.
    """
    raw = event.get("raw") or {}
    attendees = raw.get("attendees") or []
    org_domain_l = (org_domain or "").lower()
    internal_attendees: list[str] = []
    primary_external = ""
    for att in attendees:
        if not isinstance(att, dict):
            continue
        email = (att.get("email") or "").strip().lower()
        if not email:
            continue
        if att.get("optional") is True:
            # Optional attendees are often FYI CCs and should not trigger
            # high-priority change pings by themselves.
            continue
        domain = email.split("@")[-1] if "@" in email else ""
        if org_domain_l and domain == org_domain_l:
            internal_attendees.append(email)
        elif not primary_external:
            primary_external = email

    parts = [
        str(raw.get("summary", "")),
        str(raw.get("start", {}).get("dateTime") or raw.get("start_time") or ""),
        str(raw.get("end", {}).get("dateTime") or raw.get("end_time") or ""),
        str(raw.get("location", "")),
        _extract_meeting_url_for_signature(event),
        ",".join(sorted(set(internal_attendees))),
        primary_external,
        str(raw.get("status", "")).lower(),
        "1" if event.get("is_deleted") is True else "0",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _safe_parse_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_missing_identity_column_error(err: Exception) -> bool:
    text = str(err).lower()
    return (
        ("identity_key" in text or "identity_source" in text or "identity_base_key" in text or "identity_instance_key" in text)
        and ("column" in text or "schema" in text)
    )


def _is_missing_auto_join_untracked_column_error(err: Exception) -> bool:
    text = str(err).lower()
    return "auto_join_untracked" in text and ("column" in text or "schema" in text)


def _extract_webhook_sync_hint(data: dict) -> str:
    """Best-effort extraction of last-updated timestamp from calendar webhooks."""
    if not isinstance(data, dict):
        return ""
    calendar = data.get("calendar") or {}
    if not isinstance(calendar, dict):
        calendar = {}
    for key in (
        "last_updated_ts",
        "last_updated_at",
        "updated_at",
        "updated",
    ):
        val = data.get(key) or calendar.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _extract_webhook_calendar_id(data: dict) -> str:
    if not isinstance(data, dict):
        return "unknown"
    calendar_payload = data.get("calendar")
    nested_id = ""
    if isinstance(calendar_payload, dict):
        nested_id = str(calendar_payload.get("id") or "").strip()
    elif isinstance(calendar_payload, str):
        nested_id = calendar_payload.strip()
    return str(
        data.get("calendar_id")
        or nested_id
        or data.get("id")
        or "unknown"
    ).strip() or "unknown"


def _normalize_webhook_scope(value: str | None) -> str:
    text = str(value or "").strip()
    return text if text else "unknown"


def _webhook_hint_state_key(calendar_id: str | None) -> str:
    return f"{_WEBHOOK_SYNC_HINT_STATE_KEY_PREFIX}{_normalize_webhook_scope(calendar_id)}"


def _webhook_pending_state_key(calendar_id: str | None) -> str:
    return f"{_WEBHOOK_SYNC_PENDING_STATE_KEY_PREFIX}{_normalize_webhook_scope(calendar_id)}"


def _resolve_effective_poll_since(last_poll: datetime, since_hint: str | datetime | None) -> datetime:
    """Resolve poll start with bounded webhook rewind and safety overlap."""
    normalized_last_poll = _safe_parse_datetime(last_poll)
    if not normalized_last_poll:
        normalized_last_poll = datetime.now(timezone.utc) - timedelta(hours=1)
    hinted = _safe_parse_datetime(since_hint)
    if not hinted:
        return normalized_last_poll
    floor = normalized_last_poll - timedelta(seconds=WEBHOOK_SYNC_MAX_REWIND_SECONDS)
    bounded_hint = hinted if hinted >= floor else floor
    rewinded = bounded_hint - timedelta(seconds=WEBHOOK_SYNC_SAFETY_WINDOW_SECONDS)
    if rewinded < floor:
        rewinded = floor
    return rewinded if rewinded < normalized_last_poll else normalized_last_poll


def _is_hint_older_than_max_rewind(last_poll: datetime, since_hint: str | datetime | None) -> bool:
    normalized_last_poll = _safe_parse_datetime(last_poll)
    hinted = _safe_parse_datetime(since_hint)
    if not normalized_last_poll or not hinted:
        return False
    floor = normalized_last_poll - timedelta(seconds=WEBHOOK_SYNC_MAX_REWIND_SECONDS)
    return hinted < floor


def _change_flags(existing: dict, event: dict, org_domain: str = "") -> dict[str, bool]:
    raw = event.get("raw") or {}
    old_start = _safe_parse_datetime(existing.get("event_start"))
    new_start = _safe_parse_datetime(raw.get("start", {}).get("dateTime"))
    old_end = _safe_parse_datetime(existing.get("event_end"))
    new_end = _safe_parse_datetime(raw.get("end", {}).get("dateTime"))
    old_title = str(existing.get("event_title") or "")
    new_title = str(raw.get("summary") or "")
    old_meeting_url = str(existing.get("meeting_url") or "")
    new_meeting_url = _extract_meeting_url_for_signature(event)
    old_sig = str(existing.get("last_notified_signature") or "")
    new_sig = _notification_signature(event, org_domain)
    cancelled = raw.get("status") == "cancelled" or event.get("is_deleted") is True

    return {
        "title": bool(new_title and new_title != old_title),
        "time": bool(old_start and new_start and abs((new_start - old_start).total_seconds()) >= 60)
        or bool(old_end and new_end and abs((new_end - old_end).total_seconds()) >= 60),
        "meeting_url": bool(new_meeting_url and new_meeting_url != old_meeting_url),
        "cancelled": cancelled,
        "signature_changed": bool(new_sig and new_sig != old_sig),
    }


def _should_send_coalesced_change(existing: dict, flags: dict[str, bool], now: datetime) -> tuple[bool, str]:
    if not flags.get("signature_changed"):
        return False, "signature_unchanged"
    if flags.get("cancelled"):
        return True, "cancelled_force"
    if flags.get("meeting_url"):
        return True, "meeting_url_force"
    last_change = _safe_parse_datetime(existing.get("last_change_notified_at"))
    if last_change and (now - last_change).total_seconds() < CHANGE_NOTIFY_COALESCE_SECONDS:
        return False, "coalesced_recent_change"
    return True, "material_change"


def _orphan_reminder_lead_hours() -> int:
    """Configured orphan reminder lead window in hours (minimum 1h)."""
    try:
        settings = get_settings()
        return max(1, int(settings.CALENDAR_INTELLIGENCE_ORPHAN_REMINDER_LEAD_HOURS))
    except Exception:
        return 2


def _should_mark_initial_notify_as_reminded(event_start) -> bool:
    now = datetime.now(timezone.utc)
    start_dt = _safe_parse_datetime(event_start)
    if not start_dt:
        return False
    return now < start_dt <= now + timedelta(hours=_orphan_reminder_lead_hours())


def _event_has_ended(
    event: dict | None = None,
    *,
    fallback_event_end=None,
    now: datetime | None = None,
) -> bool:
    """Return True when the event end-time is at or before `now` (UTC).

    `event` can be a Recall event snapshot (`event["raw"]`) and
    `fallback_event_end` can be a stored detection `event_end` value.
    """
    raw = (event or {}).get("raw") or {}
    end_candidate = (
        raw.get("end", {}).get("dateTime")
        or raw.get("end_time")
        or fallback_event_end
    )
    end_dt = _safe_parse_datetime(end_candidate)
    if not end_dt:
        return False
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return end_dt <= ref.astimezone(timezone.utc)


def _event_signature(event: dict) -> str:
    """Content hash over the fields we care about for dedupe.

    We do NOT rely on raw.updated_at alone because providers disagree on when
    to bump it; hashing the actual scheduled content (title/time/attendees)
    guarantees a real content change forces a fresh processing attempt.

    Codex Round 6: cancellation state (`raw.status`, `is_deleted`) and the
    provider's `raw.updated` timestamp are included so that a cancelled
    version of an event and the active version cannot share a DLQ identity.
    Without this, a stale cancelled snapshot in the DLQ could be replayed
    against an event that has since been un-cancelled, triggering
    destructive cancellation handling (candidate_round cancel, bot teardown,
    detection dismissal) on live state.
    """
    raw = event.get("raw") or {}
    parts = [
        str(raw.get("summary", "")),
        str(raw.get("start", {}).get("dateTime") or raw.get("start_time") or ""),
        str(raw.get("end", {}).get("dateTime") or raw.get("end_time") or ""),
        ",".join(
            sorted(
                (a.get("email", "") or "").lower()
                for a in (raw.get("attendees") or [])
                if isinstance(a, dict)
            )
        ),
        str(raw.get("location", "")),
        _extract_meeting_url_for_signature(event),
        # Codex Round 6: cancellation state + provider version
        str(raw.get("status", "")).lower(),
        "1" if event.get("is_deleted") is True else "0",
        str(raw.get("updated", "")),
    ]
    blob = "|".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _dead_letter_key(event: dict) -> str:
    """Composite DLQ key scoped by tenant (calendar) + event id + content.

    Codex Round 4: including `calendar_id` keeps DLQ entries scoped per
    Recall calendar/tenant so one profile's dead-lettered event cannot
    suppress processing of the same upstream event id in another profile's
    context. Recall event ids are globally unique today, but this scoping
    also guards against any provider quirks that could collide ids across
    tenants and ensures the DLQ remains a per-tenant queue.
    """
    event_id = str(event.get("id") or "unknown")
    calendar_id = str(
        event.get("calendar_id")
        or (event.get("calendar") or {}).get("id", "")
        or "unknown"
    )
    return f"{calendar_id}:{event_id}:{_event_signature(event)}"


def _dead_letter_event_scope(event: dict) -> tuple[str, str]:
    """Return the (calendar_id, event_id) identity used to find co-keyed DLQ entries.

    Co-keyed = same tenant and same upstream event id but potentially different
    content signatures. Used for pruning superseded snapshots.
    """
    event_id = str(event.get("id") or "unknown")
    calendar_id = str(
        event.get("calendar_id")
        or (event.get("calendar") or {}).get("id", "")
        or "unknown"
    )
    return calendar_id, event_id


def _is_destructive_snapshot(event: dict) -> bool:
    """True if replaying this snapshot would exercise destructive cancellation handling.

    Used by the DLQ drain freshness guard: cancellation replays cancel
    candidate_rounds, tear down bots, and dismiss detections — we must not
    apply a stale cancelled snapshot to an event that has since been
    un-cancelled upstream.
    """
    raw = event.get("raw") or {}
    return raw.get("status") == "cancelled" or event.get("is_deleted") is True


def _prune_superseded_dlq_entries(
    calendar_id: str, event_id: str, current_key: str | None = None
) -> list[str]:
    """Remove all DLQ entries for (calendar_id, event_id) except `current_key`.

    Codex Round 6: multiple signatures for the same upstream event can
    accumulate in the DLQ as users edit the calendar item. Older snapshots
    must be discarded when (a) a newer version of the event is processed
    successfully in-band, (b) a new snapshot is being dead-lettered, or
    (c) a newer snapshot is successfully replayed from the DLQ. Without this,
    stale snapshots can be replayed and overwrite current state.

    Returns the list of keys that were pruned.
    """
    prefix = f"{calendar_id}:{event_id}:"
    pruned: list[str] = []
    for k in list(_dead_letter_entries.keys()):
        if not k.startswith(prefix):
            continue
        if current_key is not None and k == current_key:
            continue
        _dead_letter_entries.pop(k, None)
        pruned.append(k)
    return pruned


def _compute_next_retry(retry_count: int, now_ts: float) -> float:
    """Exponential backoff for DLQ replay, capped at _DEAD_LETTER_BACKOFF_MAX_SECONDS."""
    delay = _DEAD_LETTER_BACKOFF_INITIAL_SECONDS * (2 ** max(0, retry_count))
    delay = min(delay, _DEAD_LETTER_BACKOFF_MAX_SECONDS)
    return now_ts + delay


def _prune_expired_dead_letters(now_ts: float | None = None) -> int:
    """Drop DLQ entries older than the hard TTL. Returns count pruned.

    This is the final escape hatch for entries we can't repair. The per-entry
    retry_count also stops auto-replay after _DEAD_LETTER_MAX_RETRIES — pruning
    here just keeps the state table from growing without bound.
    """
    if now_ts is None:
        now_ts = datetime.now(timezone.utc).timestamp()
    cutoff = now_ts - _DEAD_LETTER_TTL_SECONDS
    stale = [k for k, e in _dead_letter_entries.items()
             if e.get("first_dead_lettered_at", now_ts) < cutoff]
    for k in stale:
        _dead_letter_entries.pop(k, None)
    return len(stale)


async def _persist_dead_letter_state() -> bool:
    """Write the current DLQ to Supabase for durability.

    Codex Round 6: returns True if the write completed, False on any error.
    Callers are required to propagate this status — in particular,
    `poll_and_detect` must refuse to advance `last_poll_at` when a DLQ
    persist has failed, otherwise an in-memory-only DLQ entry is lost on
    process restart and the event will never be re-delivered (incremental
    polling does not re-surface unchanged events).
    """
    try:
        supabase = get_supabase_admin_client()
        payload = json.dumps([
            {"key": k, **entry}
            for k, entry in _dead_letter_entries.items()
        ], default=str)
        await supabase.table("calendar_intelligence_state") \
            .upsert({
                "key": _DEAD_LETTER_STATE_KEY,
                "value": payload,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="key") \
            .execute_async()
        return True
    except Exception as e:
        # In-memory state still holds the entry inside the current process,
        # but on restart it is lost. Return False so callers can block
        # checkpoint advance and force the same events to be reprocessed
        # on the next poll cycle.
        logger.error(f"Calendar Intelligence: failed to persist DLQ state: {e}")
        return False


async def _hydrate_dead_letter_state() -> None:
    """Load DLQ entries from Supabase on first use after startup.

    Codex Round 5: `_dead_letter_hydrated` is ONLY flipped on a successful
    fetch+parse. A transient Supabase error previously stranded the DLQ
    for the process lifetime because the flag was set eagerly. Now a
    failure logs and leaves the flag False so the next poll retries.
    """
    global _dead_letter_hydrated
    if _dead_letter_hydrated:
        return
    try:
        supabase = get_supabase_admin_client()
        row = await supabase.table("calendar_intelligence_state") \
            .select("value") \
            .eq("key", _DEAD_LETTER_STATE_KEY) \
            .execute_async()
        # Fetch succeeded (even if empty) — mark hydrated before parsing so
        # a malformed payload doesn't cause perpetual retries on every poll.
        if not row.data:
            _dead_letter_hydrated = True
            return
        raw = row.data[0].get("value")
        if not raw:
            _dead_letter_hydrated = True
            return
        entries = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(entries, list):
            _dead_letter_hydrated = True
            return
        for item in entries:
            if not isinstance(item, dict):
                continue
            event_snapshot = item.get("event") or {}
            # Codex Round 4: recompute the key from the snapshot so that
            # entries persisted with an older (un-scoped) key schema are
            # upgraded to the new tenant-scoped key on hydrate. Falls back
            # to the stored key only when the snapshot is missing.
            if event_snapshot:
                key = _dead_letter_key(event_snapshot)
            else:
                key = item.get("key")
                if not isinstance(key, str):
                    continue
            _dead_letter_entries[key] = {
                "event": event_snapshot,
                "reason": item.get("reason", ""),
                "first_dead_lettered_at": float(item.get("first_dead_lettered_at", 0) or 0),
                "retry_count": int(item.get("retry_count", 0) or 0),
                "next_retry_at": float(item.get("next_retry_at", 0) or 0),
            }
        _prune_expired_dead_letters()
        _dead_letter_hydrated = True
        if _dead_letter_entries:
            logger.info(
                f"Calendar Intelligence: hydrated {len(_dead_letter_entries)} "
                f"DLQ entries from state table"
            )
    except Exception as e:
        # Codex Round 5: leave _dead_letter_hydrated as False so the next
        # poll_and_detect cycle retries hydration. A transient Supabase
        # blip must not permanently strand prior DLQ entries.
        logger.warning(
            "Calendar Intelligence: DLQ hydrate failed, will retry on next poll: "
            f"{e}"
        )


async def _add_to_dead_letter(event: dict, reason: str) -> bool:
    """Record a permanently-failed event with a full snapshot for replay.

    The snapshot lets the DLQ drain replay the event without re-fetching from
    Recall (which wouldn't return it — incremental polling only surfaces new
    or changed events). Logs a structured ERROR record for operator alerting.

    Codex Round 6: returns `True` only when the DLQ state has been durably
    written to Supabase. Returns `False` on persist failure so the caller
    (`poll_and_detect`) can refuse to advance `last_poll_at` — otherwise the
    in-memory DLQ entry vanishes on restart and the event is lost forever.

    Codex Round 6: when a new signature for an already-known
    (calendar_id, event_id) is inserted, older snapshots are pruned so stale
    versions cannot be replayed against current state. The caller-visible
    behavior is still a single-entry DLQ per live event, regardless of how
    many times the user edits it between processing windows.
    """
    now_ts = datetime.now(timezone.utc).timestamp()
    _prune_expired_dead_letters(now_ts)
    key = _dead_letter_key(event)

    # Codex Round 6: drop any older signatures for the same (cal, evt) before
    # inserting the new one so superseded snapshots can't be replayed later.
    calendar_id, event_id = _dead_letter_event_scope(event)
    pruned_keys = _prune_superseded_dlq_entries(calendar_id, event_id, current_key=key)
    if pruned_keys:
        logger.info(
            f"Calendar Intelligence: DLQ insert pruned {len(pruned_keys)} superseded "
            f"entries for calendar={calendar_id} event={event_id} new_key={key}"
        )

    existing = _dead_letter_entries.get(key)
    if existing:
        existing["reason"] = reason[:500]
    else:
        _dead_letter_entries[key] = {
            "event": event,
            "reason": reason[:500],
            "first_dead_lettered_at": now_ts,
            "retry_count": 0,
            "next_retry_at": _compute_next_retry(0, now_ts),
        }
        while len(_dead_letter_entries) > _DEAD_LETTER_MAX:
            oldest = next(iter(_dead_letter_entries))
            _dead_letter_entries.pop(oldest, None)

    replay_record = {
        "event": "calendar_intelligence.dead_letter",
        "key": key,
        "event_id": str(event.get("id") or ""),
        "signature": _event_signature(event),
        "reason": reason[:500],
        "dead_lettered_at": datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat(),
        "ttl_seconds": _DEAD_LETTER_TTL_SECONDS,
        "raw_summary": (event.get("raw") or {}).get("summary", ""),
        "raw_start": (event.get("raw") or {}).get("start"),
        "calendar_id": calendar_id,
    }
    logger.error(f"CAL_INTEL_DEAD_LETTER {json.dumps(replay_record, default=str)}")

    return await _persist_dead_letter_state()


# How often to renew the poll lock while draining the DLQ. Each replayed
# entry runs `_process_single_event` which can touch the network (Recall,
# Slack) so replay can easily exceed POLL_LOCK_STALE_SECONDS on a hot DLQ.
# Renewing every N processed entries keeps the lease fresh without hammering
# the lock row.
_DRAIN_LOCK_RENEW_EVERY = 5


async def _drain_dead_letter_queue(
    user_lookup,
    supabase,
    recall_cal,
    settings,
    lock_state: dict | None = None,
) -> dict:
    """Replay DLQ entries whose backoff has elapsed, before checkpoint advance.

    Returns a dict of counters {replayed, succeeded, failed, skipped_backoff,
    skipped_exhausted, skipped_stale, lock_lost, persist_failed}. Incremental
    polling (`poll_events(since=last_poll)`) does NOT refetch unchanged events,
    so the worker OWNS replay here — if we skipped this, dead-lettered events
    would be silently lost when `last_poll_at` advances past them.

    Codex Round 4: `lock_state` is an optional mutable dict of the form
    `{"token": str}`. When provided, the drain periodically renews the poll
    lock lease every `_DRAIN_LOCK_RENEW_EVERY` processed entries and aborts
    the replay if the lease is stolen (token set to None so the caller can
    skip checkpoint advance). This prevents concurrent workers from running
    when a large DLQ replay exceeds POLL_LOCK_STALE_SECONDS.

    Codex Round 6:
    - Destructive (cancellation) snapshots are checked for freshness before
      replay. If the matching `calendar_event_detections` row has been
      updated since the entry was dead-lettered, the snapshot is treated as
      stale and dropped — the DB state is the source of truth and we must
      not apply a stale cancellation on top of it.
    - A successful in-band newer-version replay purges older co-keyed DLQ
      entries so they cannot re-emerge and overwrite current state.
    - `persist_failed` is raised to the caller when the DLQ Supabase write
      fails so `poll_and_detect` can refuse to advance `last_poll_at`.
    """
    now_ts = datetime.now(timezone.utc).timestamp()
    counters = {"replayed": 0, "succeeded": 0, "failed": 0,
                "skipped_backoff": 0, "skipped_exhausted": 0,
                "exhausted_replayed": 0, "exhausted_total": 0,
                "skipped_stale": 0, "lock_lost": 0, "persist_failed": 0}
    to_remove: list[str] = []
    processed = 0
    now_dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
    for key, entry in list(_dead_letter_entries.items()):
        retry_count = int(entry.get("retry_count", 0) or 0)
        is_exhausted = retry_count >= _DEAD_LETTER_MAX_RETRIES
        if is_exhausted:
            counters["exhausted_total"] += 1

        # Codex Round 8: exhausted entries are no longer hard-skipped
        # forever. They enter a fixed low-frequency retry loop
        # (`_DEAD_LETTER_EXHAUSTED_RETRY_SECONDS`) so recovery is automatic
        # once the underlying cause (e.g. user_connection re-activation) is
        # fixed — operators do NOT have to manually clear the DLQ.
        #
        # The previous behavior would silently miss interviews indefinitely
        # for any event that hit the retry cap, even after the root cause
        # was fixed. The fixed-interval retry is a floor: the normal
        # exponential-backoff path still runs while retry_count is below
        # the cap, so this only kicks in after a prolonged failure window.
        if is_exhausted:
            last_exhausted_attempt = float(
                entry.get("last_exhausted_attempt_at", 0) or 0
            )
            if last_exhausted_attempt == 0:
                # First pass since hitting the cap — seed it so the next
                # probe happens one full interval from now, not
                # immediately. This stays aligned with the contract that
                # normal backoff was already attempted `retry_count` times.
                entry["last_exhausted_attempt_at"] = now_ts
                counters["skipped_exhausted"] += 1
                logger.warning(
                    "Calendar Intelligence: DLQ entry exhausted "
                    f"retries={retry_count} event_id={(entry.get('event') or {}).get('id')} — "
                    "switching to low-frequency auto-retry "
                    f"(interval={_DEAD_LETTER_EXHAUSTED_RETRY_SECONDS}s)"
                )
                continue
            if now_ts - last_exhausted_attempt < _DEAD_LETTER_EXHAUSTED_RETRY_SECONDS:
                counters["skipped_exhausted"] += 1
                continue
            # Interval elapsed — probe it once. On success the entry is
            # removed; on failure/defer we bump the attempt stamp and wait
            # another interval. retry_count itself is NOT incremented — the
            # entry stays flagged as exhausted for observability.
            entry["last_exhausted_attempt_at"] = now_ts
            counters["exhausted_replayed"] += 1
        elif entry.get("next_retry_at", 0) > now_ts:
            counters["skipped_backoff"] += 1
            continue

        snapshot = entry.get("event") or {}

        if _event_has_ended(snapshot, now=now_dt):
            counters["skipped_stale"] += 1
            to_remove.append(key)
            logger.info(
                "Calendar Intelligence: dropping past-event DLQ entry "
                f"event_id={snapshot.get('id')} key={key}"
            )
            continue

        # Codex Round 6: destructive-snapshot freshness guard.
        # A stale cancelled snapshot in the DLQ must NOT be replayed against
        # an event that has been un-cancelled upstream. If the matching
        # detection row was updated AFTER this entry was dead-lettered, we
        # treat the DLQ snapshot as stale and drop it — trust current DB
        # state, not the frozen snapshot.
        if _is_destructive_snapshot(snapshot):
            try:
                is_stale = await _destructive_snapshot_is_stale(snapshot, entry, supabase)
            except Exception as e:
                # If the freshness check itself fails, be conservative and
                # keep the entry around so we retry on the next poll rather
                # than apply a potentially-destructive stale replay.
                logger.warning(
                    "Calendar Intelligence: DLQ freshness check errored for "
                    f"event_id={snapshot.get('id')}, deferring replay: {e}"
                )
                continue
            if is_stale:
                counters["skipped_stale"] += 1
                to_remove.append(key)
                logger.warning(
                    "Calendar Intelligence: dropping stale cancellation DLQ "
                    f"entry event_id={snapshot.get('id')} key={key} — "
                    "detection was updated after dead-letter"
                )
                continue

        # Codex Round 5: Renew the poll lock BEFORE running the first
        # replay AND every N processed entries thereafter. The previous gate
        # required `processed > 0`, so the very first replay ran without
        # renewal — if it was slow, the lease could expire and another
        # worker would concurrently acquire the lock. Eager first-renewal
        # caps the time since lock acquisition to at most one replay latency.
        if (
            lock_state is not None
            and lock_state.get("token")
            and processed % _DRAIN_LOCK_RENEW_EVERY == 0
        ):
            new_token = await _renew_poll_lock(lock_state["token"])
            if new_token is None:
                counters["lock_lost"] = 1
                lock_state["token"] = None
                logger.error(
                    "Calendar Intelligence: poll lock lost during DLQ drain "
                    f"after {processed} replays, aborting remaining queue"
                )
                break
            lock_state["token"] = new_token

        counters["replayed"] += 1
        processed += 1
        try:
            outcome = await _process_single_event(snapshot, user_lookup, supabase, recall_cal, settings)
            # Codex Round 7: only remove the entry on an explicit terminal
            # outcome. A "defer" outcome means the event could not be
            # processed this cycle (e.g. missing user_lookup mapping because
            # the user_connection is briefly inactive) and MUST be retried;
            # treating it as success silently loses the event.
            #
            # Legacy callers (and the existing unit test suite that mocks
            # `_process_single_event` via `AsyncMock` with no return value)
            # return `None`/`MagicMock` — anything that isn't the literal
            # string `"defer"` is considered terminal so we stay backwards
            # compatible with those call sites.
            if outcome == "defer":
                counters["failed"] += 1
                # Codex Round 8: do NOT bump retry_count past the cap —
                # exhausted entries stay flagged as exhausted. The
                # low-frequency re-probe already updated
                # `last_exhausted_attempt_at` at entry selection time.
                if not is_exhausted:
                    entry["retry_count"] = int(entry.get("retry_count", 0)) + 1
                    entry["next_retry_at"] = _compute_next_retry(entry["retry_count"], now_ts)
                entry["reason"] = f"deferred: {entry.get('reason', 'retriable early-return')}"[:500]
                logger.warning(
                    f"Calendar Intelligence: DLQ replay deferred for "
                    f"event_id={snapshot.get('id')} retry={entry['retry_count']} "
                    f"exhausted={is_exhausted}"
                )
                continue

            counters["succeeded"] += 1
            to_remove.append(key)
            if is_exhausted:
                logger.info(
                    "Calendar Intelligence: previously-exhausted DLQ entry "
                    f"RECOVERED event_id={snapshot.get('id')} key={key} — "
                    "root cause appears fixed"
                )
            # Codex Round 6: a successful replay means this snapshot is now
            # reflected in DB state. Any older snapshots for the same
            # (calendar, event) in the DLQ are therefore superseded and must
            # be discarded so they cannot later overwrite current state.
            calendar_id, event_id = _dead_letter_event_scope(snapshot)
            pruned = _prune_superseded_dlq_entries(calendar_id, event_id, current_key=key)
            if pruned:
                logger.info(
                    "Calendar Intelligence: DLQ replay succeeded, pruned "
                    f"{len(pruned)} superseded entries for calendar={calendar_id} "
                    f"event={event_id}"
                )
                # Also remove pruned keys from the to_remove list to avoid
                # double-popping a no-longer-present key (harmless but noisy).
                pruned_set = set(pruned)
                to_remove = [k for k in to_remove if k not in pruned_set]
            logger.info(
                f"Calendar Intelligence: DLQ replay succeeded for "
                f"event_id={snapshot.get('id')} key={key} outcome={outcome}"
            )
        except Exception as e:
            counters["failed"] += 1
            if not is_exhausted:
                entry["retry_count"] = int(entry.get("retry_count", 0)) + 1
                entry["next_retry_at"] = _compute_next_retry(entry["retry_count"], now_ts)
            entry["reason"] = f"{type(e).__name__}: {e}"[:500]
            logger.warning(
                f"Calendar Intelligence: DLQ replay failed for "
                f"event_id={snapshot.get('id')} retry={entry['retry_count']} "
                f"exhausted={is_exhausted}: {e}"
            )

    for key in to_remove:
        _dead_letter_entries.pop(key, None)

    if counters["replayed"] or to_remove:
        persisted = await _persist_dead_letter_state()
        if not persisted:
            counters["persist_failed"] = 1

    return counters


async def _destructive_snapshot_is_stale(
    snapshot: dict, entry: dict, supabase
) -> bool:
    """Return True if the matching detection row is newer than the DLQ entry.

    Used by `_drain_dead_letter_queue` to avoid applying a stale cancelled
    snapshot against an event that has been un-cancelled upstream. Conservative
    fallbacks:
    - No `recall_event_id` → cannot check, treat as fresh (caller will replay).
    - No `recall_calendar_id` on the snapshot → cannot safely tenant-scope
      the query; conservatively treat as fresh so the caller's destructive
      replay path runs (the DB CAS inside `_check_reschedule` is the
      secondary safety net).
    - No detection row → treat as fresh (nothing to overwrite).
    - Missing/unparseable `updated_at` → treat as fresh (no evidence of
      conflict; DB CAS inside `_check_reschedule` is a secondary safety net).

    Codex Round 7: the query is tenant/calendar scoped using
    `recall_calendar_id` so that same-`recall_event_id` rows belonging to a
    different calendar/tenant cannot pollute the staleness check. The DLQ
    key is calendar-scoped (see `_dead_letter_key`), so the staleness query
    must use the same identity or the two checks can disagree and drop a
    legitimate cancellation replay under an ID collision.
    """
    recall_event_id = str(snapshot.get("id") or "")
    if not recall_event_id:
        return False

    calendar_id, _ = _dead_letter_event_scope(snapshot)
    # `_dead_letter_event_scope` returns the sentinel "unknown" when the
    # snapshot has no extractable calendar_id. Treat that the same as empty
    # so we don't run a one-sided tenant-scoped query that could still pull
    # unrelated rows if the sentinel ever leaked into the DB.
    if not calendar_id or calendar_id == "unknown":
        # Cannot scope to a single tenant/calendar — avoid using a
        # cross-tenant row as evidence of staleness.
        return False

    dead_lettered_at = float(entry.get("first_dead_lettered_at", 0) or 0)
    if dead_lettered_at <= 0:
        return False

    rows = await supabase.table("calendar_event_detections") \
        .select("updated_at, detection_status") \
        .eq("recall_event_id", recall_event_id) \
        .eq("recall_calendar_id", calendar_id) \
        .execute_async()
    if not rows.data:
        return False

    for row in rows.data:
        # A row already in a terminal dismissed state is consistent with the
        # cancellation snapshot — let replay be a no-op; don't mark stale.
        if row.get("detection_status") == "dismissed":
            continue
        updated_at_raw = row.get("updated_at")
        if not updated_at_raw:
            continue
        try:
            updated_dt = datetime.fromisoformat(
                str(updated_at_raw).replace("Z", "+00:00")
            )
            updated_ts = updated_dt.timestamp()
        except (ValueError, TypeError):
            continue
        if updated_ts > dead_lettered_at:
            return True
    return False

async def _try_acquire_poll_lock() -> str | None:
    """Returns lock token (ISO timestamp) on success, None on failure."""
    supabase = get_supabase_admin_client()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    lock_result = await supabase.table("calendar_intelligence_state") \
        .update({"value": now_iso, "updated_at": now_iso}) \
        .eq("key", "poll_locked_at") \
        .is_("value", "null") \
        .execute_async()

    if lock_result.data:
        return now_iso

    row = await supabase.table("calendar_intelligence_state") \
        .select("value") \
        .eq("key", "poll_locked_at") \
        .execute_async()
    locked_at = row.data[0].get("value") if row.data else None

    if locked_at:
        try:
            locked_time = datetime.fromisoformat(locked_at)
            age = (now - locked_time.astimezone(timezone.utc)).total_seconds()
            if age > POLL_LOCK_STALE_SECONDS:
                lock_result = await supabase.table("calendar_intelligence_state") \
                    .update({"value": now_iso, "updated_at": now_iso}) \
                    .eq("key", "poll_locked_at") \
                    .eq("value", locked_at) \
                    .execute_async()
                return now_iso if lock_result.data else None
        except (ValueError, TypeError):
            pass

    return None


async def _renew_poll_lock(token: str) -> str | None:
    """Extend lock lease by updating the timestamp if we still hold it. Returns None on CAS miss."""
    supabase = get_supabase_admin_client()
    new_token = datetime.now(timezone.utc).isoformat()
    result = await supabase.table("calendar_intelligence_state") \
        .update({"value": new_token, "updated_at": new_token}) \
        .eq("key", "poll_locked_at") \
        .eq("value", token) \
        .execute_async()
    if result.data:
        return new_token
    logger.warning("Calendar Intelligence: lock renewal CAS failed — lock was stolen")
    return None


async def _release_poll_lock(token: str):
    """CAS release: only clears the lock if it still holds our token."""
    supabase = get_supabase_admin_client()
    await supabase.table("calendar_intelligence_state") \
        .update({"value": None, "updated_at": datetime.now(timezone.utc).isoformat()}) \
        .eq("key", "poll_locked_at") \
        .eq("value", token) \
        .execute_async()


async def _get_pending_webhook_sync_hint_rows() -> list[dict]:
    """Return all pending scoped webhook hint rows plus legacy global row."""
    supabase = get_supabase_admin_client()
    rows: list[dict] = []

    scoped = await supabase.table("calendar_intelligence_state") \
        .select("key, value") \
        .ilike("key", f"{_WEBHOOK_SYNC_HINT_STATE_KEY_PREFIX}%") \
        .execute_async()
    for item in (scoped.data or []):
        key = str(item.get("key") or "").strip()
        if not key.startswith(_WEBHOOK_SYNC_HINT_STATE_KEY_PREFIX):
            continue
        raw_val = str(item.get("value") or "").strip()
        rows.append({
            "key": key,
            "calendar_id": key[len(_WEBHOOK_SYNC_HINT_STATE_KEY_PREFIX):] or "unknown",
            "raw": raw_val,
            "dt": _safe_parse_datetime(raw_val),
        })

    legacy = await supabase.table("calendar_intelligence_state") \
        .select("key, value") \
        .eq("key", _WEBHOOK_SYNC_HINT_STATE_KEY) \
        .execute_async()
    for item in (legacy.data or []):
        key = str(item.get("key") or "").strip()
        raw_val = str(item.get("value") or "").strip()
        rows.append({
            "key": key,
            "calendar_id": "legacy",
            "raw": raw_val,
            "dt": _safe_parse_datetime(raw_val),
        })

    return rows


async def _get_pending_webhook_sync_hint_row() -> tuple[str, datetime | None]:
    """Backward-compatible helper: return earliest raw+parsed pending hint."""
    rows = await _get_pending_webhook_sync_hint_rows()
    dated = [r for r in rows if r.get("dt")]
    if not dated:
        return "", None
    dated.sort(key=lambda r: r["dt"])
    first = dated[0]
    return str(first.get("raw") or "").strip(), first.get("dt")


async def _merge_pending_webhook_sync_hint(ts: datetime, *, calendar_id: str | None = None) -> None:
    """Persist earliest pending webhook hint (scoped by calendar) with CAS retries."""
    hint_utc = ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    hint_iso = hint_utc.isoformat()
    state_key = _webhook_hint_state_key(calendar_id)
    supabase = get_supabase_admin_client()

    for _ in range(WEBHOOK_SYNC_HINT_MERGE_MAX_RETRIES):
        row = await supabase.table("calendar_intelligence_state") \
            .select("value") \
            .eq("key", state_key) \
            .execute_async()

        row_exists = bool(row.data)
        current_val = row.data[0].get("value") if row_exists else None
        current_raw = str(current_val or "").strip()
        current_dt = _safe_parse_datetime(current_raw)

        if current_dt and current_dt <= hint_utc:
            return

        payload = {
            "value": hint_iso,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        if row_exists:
            q = supabase.table("calendar_intelligence_state") \
                .update(payload) \
                .eq("key", state_key)
            if current_raw:
                result = await q.eq("value", current_raw).execute_async()
            else:
                result = await q.is_("value", "null").execute_async()
            if result.data:
                return
        else:
            try:
                result = await supabase.table("calendar_intelligence_state") \
                    .insert({"key": state_key, **payload}) \
                    .execute_async()
                if result.data:
                    return
            except Exception:
                # Concurrent insert/update won. Re-read and retry CAS merge.
                pass

        await asyncio.sleep(0)

    logger.warning(
        "Calendar Intelligence: webhook hint merge retries exhausted; "
        "keeping existing pending hint key=%s hint=%s",
        state_key,
        hint_iso,
    )


async def _mark_pending_webhook_update(calendar_id: str | None) -> None:
    """Persist hintless update marker so webhook ingress is durable."""
    state_key = _webhook_pending_state_key(calendar_id)
    supabase = get_supabase_admin_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    await supabase.table("calendar_intelligence_state") \
        .upsert({
            "key": state_key,
            "value": now_iso,
            "updated_at": now_iso,
        }, on_conflict="key") \
        .execute_async()


async def _get_pending_webhook_update_flag_rows() -> list[dict]:
    supabase = get_supabase_admin_client()
    rows: list[dict] = []
    result = await supabase.table("calendar_intelligence_state") \
        .select("key, value") \
        .ilike("key", f"{_WEBHOOK_SYNC_PENDING_STATE_KEY_PREFIX}%") \
        .execute_async()
    for item in (result.data or []):
        key = str(item.get("key") or "").strip()
        if not key.startswith(_WEBHOOK_SYNC_PENDING_STATE_KEY_PREFIX):
            continue
        rows.append({"key": key, "raw": str(item.get("value") or "").strip()})
    return rows


async def _clear_pending_webhook_sync_hint_if_unchanged(state_key: str, raw_value: str) -> None:
    """Clear pending hint only if it wasn't replaced while current poll was running."""
    if not state_key:
        return
    supabase = get_supabase_admin_client()
    query = supabase.table("calendar_intelligence_state") \
        .update({"value": None, "updated_at": datetime.now(timezone.utc).isoformat()}) \
        .eq("key", state_key)
    if raw_value:
        await query.eq("value", raw_value).execute_async()
    else:
        await query.is_("value", "null").execute_async()


async def _clear_pending_webhook_update_flag_if_unchanged(state_key: str, raw_value: str) -> None:
    if not state_key:
        return
    supabase = get_supabase_admin_client()
    query = supabase.table("calendar_intelligence_state") \
        .update({"value": None, "updated_at": datetime.now(timezone.utc).isoformat()}) \
        .eq("key", state_key)
    if raw_value:
        await query.eq("value", raw_value).execute_async()
    else:
        await query.is_("value", "null").execute_async()


async def _get_last_poll_at() -> datetime:
    supabase = get_supabase_admin_client()
    row = await supabase.table("calendar_intelligence_state") \
        .select("value") \
        .eq("key", "last_poll_at") \
        .execute_async()
    if row.data and row.data[0].get("value"):
        parsed = _safe_parse_datetime(row.data[0].get("value"))
        if parsed:
            return parsed
    return datetime.now(timezone.utc) - timedelta(hours=1)


async def _set_last_poll_at(ts: datetime):
    supabase = get_supabase_admin_client()
    await supabase.table("calendar_intelligence_state") \
        .update({"value": ts.isoformat(), "updated_at": datetime.now(timezone.utc).isoformat()}) \
        .eq("key", "last_poll_at") \
        .execute_async()


async def _batch_user_lookups(calendar_ids: list[str]) -> dict[str, dict]:
    if not calendar_ids:
        return {}
    supabase = get_supabase_admin_client()
    try:
        result = await supabase.table("user_connections") \
            .select("recall_calendar_id, profile_id, organization_id, provider_email, auto_join_untracked") \
            .in_("recall_calendar_id", calendar_ids) \
            .eq("provider", "google_calendar") \
            .eq("is_active", True) \
            .eq("calendar_watch_enabled", True) \
            .execute_async()
    except Exception as lookup_err:
        if not _is_missing_auto_join_untracked_column_error(lookup_err):
            raise
        result = await supabase.table("user_connections") \
            .select("recall_calendar_id, profile_id, organization_id, provider_email") \
            .in_("recall_calendar_id", calendar_ids) \
            .eq("provider", "google_calendar") \
            .eq("is_active", True) \
            .eq("calendar_watch_enabled", True) \
            .execute_async()

    profile_ids = [str(r.get("profile_id")) for r in (result.data or []) if r.get("profile_id")]
    profile_tz_by_id: dict[str, str] = {}
    if profile_ids:
        profiles = await supabase.table("profiles") \
            .select("id, timezone") \
            .in_("id", profile_ids) \
            .execute_async()
        for row in (profiles.data or []):
            pid = str(row.get("id"))
            if pid:
                profile_tz_by_id[pid] = row.get("timezone") or ""

    lookup = {}
    for row in (result.data or []):
        cal_id = row.get("recall_calendar_id")
        if cal_id:
            pid = str(row["profile_id"])
            lookup[cal_id] = {
                "profile_id": row["profile_id"],
                "organization_id": row["organization_id"],
                "provider_email": row.get("provider_email", ""),
                "auto_join_untracked": row.get("auto_join_untracked"),
                "timezone": profile_tz_by_id.get(pid, ""),
            }
    return lookup


async def _is_calendar_connected(recall_cal, calendar_id: str) -> bool:
    """Best-effort guard: skip processing if Recall reports disconnected."""
    if not calendar_id:
        return True
    now_ts = datetime.now(timezone.utc).timestamp()
    cached = _calendar_status_cache.get(calendar_id)
    if cached and (now_ts - cached[1]) < _CALENDAR_STATUS_CACHE_TTL_SECONDS:
        return cached[0] != "disconnected"

    try:
        status_payload = await recall_cal.get_calendar_status(calendar_id)
        status = str((status_payload or {}).get("status") or "").strip().lower()
    except Exception as e:
        # Fail open on status probe errors so we do not stall processing.
        logger.warning(
            f"Calendar Intelligence: status probe failed for calendar={calendar_id}: {e}"
        )
        status = ""

    _calendar_status_cache[calendar_id] = (status, now_ts)
    return status != "disconnected"


async def enqueue_calendar_sync_hint(event_type: str, data: dict | None = None) -> dict:
    """Durably record webhook sync intent before webhook ACK."""
    settings = get_settings()
    if not settings.CALENDAR_INTELLIGENCE_ENABLED:
        logger.info("Calendar Intelligence: webhook hint ignored (disabled) event=%s", event_type)
        return {"calendar_id": "unknown", "hint_dt": None}

    payload = data if isinstance(data, dict) else {}
    calendar_id = _extract_webhook_calendar_id(payload)
    hint_text = _extract_webhook_sync_hint(payload)
    hint_dt = _safe_parse_datetime(hint_text)
    if hint_dt:
        last_poll = await _get_last_poll_at()
        if _is_hint_older_than_max_rewind(last_poll, hint_dt):
            logger.warning(
                "Calendar Intelligence: received stale webhook hint outside max rewind "
                "event=%s hint=%s last_poll=%s max_rewind_s=%s",
                event_type,
                hint_dt.isoformat(),
                last_poll.isoformat(),
                WEBHOOK_SYNC_MAX_REWIND_SECONDS,
            )
        await _merge_pending_webhook_sync_hint(hint_dt, calendar_id=calendar_id)
    else:
        # Hintless calendar updates are persisted as lightweight pending flags
        # and consumed by the scheduled poll (no immediate full poll here).
        await _mark_pending_webhook_update(calendar_id)
    return {"calendar_id": calendar_id, "hint_dt": hint_dt}


async def process_calendar_sync_hint(event_type: str, data: dict | None = None):
    """Best-effort immediate sync pass for hinted webhooks only."""
    settings = get_settings()
    if not settings.CALENDAR_INTELLIGENCE_ENABLED:
        logger.info("Calendar Intelligence: webhook hint ignored (disabled) event=%s", event_type)
        return

    payload = data if isinstance(data, dict) else {}
    hint_text = _extract_webhook_sync_hint(payload)
    hint_dt = _safe_parse_datetime(hint_text)
    if not hint_dt:
        logger.info(
            "Calendar Intelligence: webhook immediate poll skipped (no hint) event=%s",
            event_type,
        )
        return
    await poll_and_detect(since_hint=hint_dt, source=f"webhook:{event_type}")


async def poll_and_detect(*, since_hint: str | datetime | None = None, source: str = "scheduler"):
    lock_token = await _try_acquire_poll_lock()
    if not lock_token:
        logger.debug("Calendar Intelligence poll lock held by another worker, skipping")
        return

    try:
        settings = get_settings()
        if not settings.CALENDAR_INTELLIGENCE_ENABLED:
            return

        # Rebuild DLQ map from Supabase once per process so restarts don't
        # forget permanently-failed events. Cheap (one row read).
        await _hydrate_dead_letter_state()
        _prune_expired_dead_letters()

        recall_cal = get_recall_calendar_service()
        try:
            supabase = get_supabase_admin_client()
            last_poll = await _get_last_poll_at()
            pending_hint_rows = await _get_pending_webhook_sync_hint_rows()
            pending_update_rows = await _get_pending_webhook_update_flag_rows()
            stale_pending_hint_rows = [
                r for r in pending_hint_rows
                if _is_hint_older_than_max_rewind(last_poll, r.get("dt"))
            ]
            effective_since = last_poll
            hinted_since = _resolve_effective_poll_since(last_poll, since_hint)
            if hinted_since < effective_since:
                effective_since = hinted_since
            for pending_row in pending_hint_rows:
                pending_dt = pending_row.get("dt")
                if not pending_dt:
                    continue
                pending_since = _resolve_effective_poll_since(last_poll, pending_dt)
                if pending_since < effective_since:
                    effective_since = pending_since
            poll_start = datetime.now(timezone.utc)
            if effective_since != last_poll:
                logger.info(
                    "Calendar Intelligence: poll override from %s source=%s effective_since=%s base_last_poll=%s",
                    since_hint,
                    source,
                    effective_since.isoformat(),
                    last_poll.isoformat(),
                )

            events, poll_complete = await recall_cal.poll_events(since=effective_since)

            calendar_ids = list({e.get("calendar_id") or e.get("calendar", {}).get("id", "") for e in events if e.get("calendar_id") or e.get("calendar", {}).get("id")})
            # Extend the lookup with calendar_ids from DLQ snapshots so replay
            # can still resolve users for events not in the current batch.
            for entry in _dead_letter_entries.values():
                snap = entry.get("event") or {}
                cid = snap.get("calendar_id") or (snap.get("calendar") or {}).get("id")
                if cid and cid not in calendar_ids:
                    calendar_ids.append(cid)
            user_lookup = await _batch_user_lookups(calendar_ids) if calendar_ids else {}

            failed_event_ids = []
            dead_lettered_this_poll = 0
            lock_lost = False
            # Codex Round 6: track any DLQ persistence failures from in-band
            # dead-lettering. A failed persist means the entry lives only in
            # process memory and would be lost on restart — we must refuse to
            # advance `last_poll_at` so the event gets reprocessed on the
            # next cycle instead of being silently dropped.
            dlq_persist_failed = False
            for idx, event in enumerate(events):
                if idx > 0 and idx % 10 == 0:
                    renewed = await _renew_poll_lock(lock_token)
                    if renewed is None:
                        logger.error("Calendar Intelligence: lock stolen during processing, aborting batch")
                        lock_lost = True
                        break
                    lock_token = renewed

                event_id = event.get("id", "unknown")
                event_calendar_id = str(
                    event.get("calendar_id")
                    or (event.get("calendar") or {}).get("id")
                    or ""
                )
                if event_calendar_id and not await _is_calendar_connected(recall_cal, event_calendar_id):
                    logger.info(
                        "Calendar Intelligence: skipping event from disconnected "
                        f"calendar={event_calendar_id} event={event_id}"
                    )
                    continue
                dl_key = _dead_letter_key(event)
                # Composite key: if the calendar event was edited upstream, the
                # signature changes and the event is reprocessed instead of
                # being silently skipped. The DLQ drain below replays entries
                # whose content did NOT change, so we don't lose them.
                if dl_key in _dead_letter_entries:
                    dead_lettered_this_poll += 1
                    continue

                try:
                    outcome = await _process_single_event(event, user_lookup, supabase, recall_cal, settings)
                    # Codex Round 7: a "defer" outcome means the event hit a
                    # retriable early-return (e.g. missing user_lookup
                    # mapping or empty insert result). Treat it exactly like
                    # a raised exception so the event is retry-counted and
                    # eventually dead-lettered for later replay — advancing
                    # the checkpoint past a deferred event would lose it.
                    if outcome == "defer":
                        fail_key = dl_key
                        _event_fail_counts[fail_key] = _event_fail_counts.get(fail_key, 0) + 1
                        if _event_fail_counts[fail_key] >= MAX_EVENT_RETRIES:
                            logger.error(
                                f"Calendar Intelligence: event {event_id} deferred "
                                f"{MAX_EVENT_RETRIES} times, dead-lettering"
                            )
                            _event_fail_counts.pop(fail_key, None)
                            persisted = await _add_to_dead_letter(
                                event, reason="deferred: retriable early-return"
                            )
                            if not persisted:
                                dlq_persist_failed = True
                                logger.error(
                                    "Calendar Intelligence: dead-letter persist "
                                    f"failed for deferred event {event_id}, "
                                    "blocking checkpoint advance"
                                )
                        else:
                            failed_event_ids.append(event_id)
                            logger.warning(
                                f"Calendar Intelligence: event {event_id} deferred "
                                f"(attempt {_event_fail_counts[fail_key]})"
                            )
                        continue

                    # Codex Round 6: successful in-band processing means the
                    # current snapshot is reflected in DB state. Any older
                    # co-keyed DLQ entries (stale signatures for the same
                    # calendar+event) are now superseded and must be dropped
                    # before they can be replayed and overwrite live state.
                    # Codex Round 7: gated on outcome != "defer" (handled
                    # above) so a deferred event does NOT prune older DLQ
                    # snapshots — the defer means DB state was not written.
                    calendar_id, upstream_event_id = _dead_letter_event_scope(event)
                    pruned_keys = _prune_superseded_dlq_entries(
                        calendar_id, upstream_event_id, current_key=None
                    )
                    if pruned_keys:
                        logger.info(
                            "Calendar Intelligence: in-band success pruned "
                            f"{len(pruned_keys)} superseded DLQ entries for "
                            f"calendar={calendar_id} event={upstream_event_id}"
                        )
                        persisted = await _persist_dead_letter_state()
                        if not persisted:
                            dlq_persist_failed = True
                except Exception as e:
                    fail_key = dl_key  # count retries per (event_id, signature)
                    _event_fail_counts[fail_key] = _event_fail_counts.get(fail_key, 0) + 1
                    if _event_fail_counts[fail_key] >= MAX_EVENT_RETRIES:
                        logger.error(
                            f"Calendar Intelligence: event {event_id} failed "
                            f"{MAX_EVENT_RETRIES} times, dead-lettering: {e}"
                        )
                        _event_fail_counts.pop(fail_key, None)
                        persisted = await _add_to_dead_letter(
                            event, reason=f"{type(e).__name__}: {e}"
                        )
                        if not persisted:
                            # Codex Round 6: DLQ write failed — we cannot
                            # advance the checkpoint past this event or it
                            # would be lost forever. Track and gate below.
                            dlq_persist_failed = True
                            logger.error(
                                "Calendar Intelligence: dead-letter persist "
                                f"failed for event {event_id}, blocking "
                                "checkpoint advance"
                            )
                    else:
                        failed_event_ids.append(event_id)
                        logger.warning(f"Calendar Intelligence: event {event_id} failed (attempt {_event_fail_counts[fail_key]}): {e}")

            if dead_lettered_this_poll:
                logger.warning(
                    f"Calendar Intelligence: skipped {dead_lettered_this_poll} DLQ-known events this poll (will replay on backoff)"
                )

            # Drain replay queue BEFORE advancing the checkpoint. This is the
            # key invariant that makes checkpoint advance safe: dead-lettered
            # events are durably owned by the DLQ and replayed here, so the
            # cursor can advance without losing them. Incremental polling does
            # not re-surface unchanged events, so replay MUST happen here.
            # Codex Round 4: pass lock_state so drain renews the lease during
            # long replays and aborts if another worker steals the lock.
            lock_state = {"token": lock_token}
            drain = await _drain_dead_letter_queue(
                user_lookup, supabase, recall_cal, settings, lock_state=lock_state,
            )
            if drain["replayed"]:
                logger.info(
                    f"Calendar Intelligence: DLQ drain replayed={drain['replayed']} "
                    f"succeeded={drain['succeeded']} failed={drain['failed']}"
                )
            if drain.get("lock_lost"):
                lock_lost = True
            # Codex Round 6: drain-side persistence failure also blocks the
            # checkpoint — otherwise entries that were mutated (retry count,
            # next_retry_at) only in memory would lose their backoff state
            # on restart and get replayed immediately on the next poll.
            if drain.get("persist_failed"):
                dlq_persist_failed = True
            # Track any renewed lock token so _release_poll_lock in the outer
            # finally block uses the current token (the old one is invalid
            # after renewal CAS).
            if lock_state.get("token"):
                lock_token = lock_state["token"]

            if lock_lost:
                logger.warning("Calendar Intelligence: lock lost, skipping checkpoint advance")
            elif dlq_persist_failed:
                # Codex Round 6: do NOT advance last_poll_at if any DLQ
                # persistence failed. The in-memory entry would vanish on
                # restart and the underlying events would be permanently
                # lost — incremental polling does not re-surface them.
                logger.error(
                    "Calendar Intelligence: DLQ persistence failed, "
                    "blocking checkpoint advance so events will be "
                    "reprocessed on next poll"
                )
            elif poll_complete and not failed_event_ids:
                # Checkpoint advances now that (a) in-band events are processed,
                # (b) previously dead-lettered events have been replayed via the
                # DLQ drain, (c) any that failed replay remain durably
                # enqueued for the next cycle with exponential backoff, and
                # (d) all DLQ state writes have confirmed durability.
                await _set_last_poll_at(poll_start)
                for pending_row in pending_hint_rows:
                    await _clear_pending_webhook_sync_hint_if_unchanged(
                        str(pending_row.get("key") or ""),
                        str(pending_row.get("raw") or ""),
                    )
                for pending_update in pending_update_rows:
                    await _clear_pending_webhook_update_flag_if_unchanged(
                        str(pending_update.get("key") or ""),
                        str(pending_update.get("raw") or ""),
                    )
                _event_fail_counts.clear()
            elif failed_event_ids:
                logger.warning(f"Calendar Intelligence: {len(failed_event_ids)}/{len(events)} events blocking checkpoint (ids: {failed_event_ids[:10]})")
                if (
                    not poll_complete
                    and stale_pending_hint_rows
                ):
                    logger.error(
                        "Calendar Intelligence: partial poll with stale hint; clearing pending hint "
                        "to prevent replay loop stale_count=%s",
                        len(stale_pending_hint_rows),
                    )
                    for stale_row in stale_pending_hint_rows:
                        await _clear_pending_webhook_sync_hint_if_unchanged(
                            str(stale_row.get("key") or ""),
                            str(stale_row.get("raw") or ""),
                        )
            else:
                logger.warning("Calendar Intelligence: poll incomplete, checkpoint NOT advanced")
                if stale_pending_hint_rows:
                    logger.error(
                        "Calendar Intelligence: incomplete poll with stale hint; clearing pending hint "
                        "to prevent replay loop stale_count=%s",
                        len(stale_pending_hint_rows),
                    )
                    for stale_row in stale_pending_hint_rows:
                        await _clear_pending_webhook_sync_hint_if_unchanged(
                            str(stale_row.get("key") or ""),
                            str(stale_row.get("raw") or ""),
                        )
        finally:
            await recall_cal.close()

    except Exception as e:
        logger.error(f"Calendar Intelligence poll_and_detect error: {e}", exc_info=True)
    finally:
        await _release_poll_lock(lock_token)


async def _process_single_event(
    event: dict, user_lookup: dict, supabase, recall_cal, settings
) -> ProcessingOutcome:
    """Process one calendar event end-to-end.

    Codex Round 7: returns a `ProcessingOutcome` string (`"processed"`,
    `"defer"`, or `"drop"`) so `_drain_dead_letter_queue` can distinguish
    "successfully handled / intentional no-op" from "could not process this
    time — retry later". A bare `return` was previously interpreted as
    success, which silently dropped events that hit a retriable early
    return (e.g. missing `user_lookup` for a user whose connection went
    inactive mid-poll).
    """
    recall_event_id = str(event.get("id", ""))
    if not recall_event_id:
        # Malformed event — cannot key a DLQ entry anyway. Drop.
        return "drop"

    calendar_id = event.get("calendar_id") or event.get("calendar", {}).get("id", "")
    user_info = user_lookup.get(str(calendar_id))
    if not user_info:
        # Codex Round 7: the user's calendar connection is not in the lookup
        # (deactivated, deleted, or a transient DB miss during the batch
        # build). Do NOT mark the event as processed — keep it in the DLQ
        # with exponential backoff so a re-activation is recoverable.
        logger.warning(
            f"Calendar Intelligence: deferring event={recall_event_id} — "
            f"no user_lookup mapping for calendar_id={calendar_id}"
        )
        return "defer"

    profile_id = user_info["profile_id"]
    org_id = user_info["organization_id"]
    provider_email = user_info.get("provider_email", "")
    profile_timezone = user_info.get("timezone", "")
    org_domain = provider_email.split("@")[-1] if "@" in provider_email else ""

    if not org_domain:
        # Broken user_connection — `provider_email` is empty or malformed.
        # Codex Round 7: this might be fixed by the user reconnecting, so
        # defer the event instead of silently dropping it.
        logger.warning(
            f"Calendar Intelligence: deferring event={recall_event_id} — "
            f"empty org_domain for profile={profile_id}"
        )
        return "defer"

    # Stable identities used for reconnect-safe dedupe.
    stable_platform_id = _stable_platform_id(event)
    stable_ical_uid = _stable_ical_uid(event)
    identity_source, identity_base_key, identity_instance_key, identity_compound_key = _canonical_event_identity(event)

    if calendar_id and not await _is_calendar_connected(recall_cal, str(calendar_id)):
        logger.info(
            "Calendar Intelligence: deferring event=%s from disconnected calendar=%s",
            recall_event_id,
            calendar_id,
        )
        return "defer"

    raw = event.get("raw", {})
    organizer_email = raw.get("organizer", {}).get("email", "").lower()
    if organizer_email and organizer_email != provider_email.lower():
        organizer_in_lookup = any(
            info.get("provider_email", "").lower() == organizer_email
            and str(info.get("organization_id")) == str(org_id)
            for info in user_lookup.values()
        )
        if organizer_in_lookup:
            # Another user in the same org owns this event — intentional
            # no-op so the organizer handles it exactly once.
            return "processed"

        organizer_conn = await supabase.table("user_connections") \
            .select("id, calendar_watch_enabled, organization_id") \
            .eq("provider_email", organizer_email) \
            .eq("provider", "google_calendar") \
            .eq("is_active", True) \
            .eq("calendar_watch_enabled", True) \
            .execute_async()
        if organizer_conn.data and any(str(c.get("organization_id")) == str(org_id) for c in organizer_conn.data):
            # Same organizer-deduplication case — intentional no-op.
            return "processed"

    select_fields = (
        "id, detection_status, event_title, event_start, event_end, meeting_url, "
        "slack_message_ts, slack_channel_id, notified_at, internal_attendees, "
        "external_attendees, profile_id, matched_candidate_round_id, "
        "recall_event_id, platform_event_id, platform_id, ical_uid, "
        "last_notified_signature, last_change_notified_at, detection_signals"
    )
    existing = None
    if identity_compound_key:
        try:
            existing = await supabase.table("calendar_event_detections") \
                .select(select_fields) \
                .eq("identity_key", identity_compound_key) \
                .eq("profile_id", profile_id) \
                .order("updated_at", desc=True) \
                .limit(1) \
                .execute_async()
        except Exception as identity_err:
            if not _is_missing_identity_column_error(identity_err):
                raise
    if not existing or not existing.data:
        existing = await supabase.table("calendar_event_detections") \
            .select(select_fields) \
            .eq("recall_event_id", recall_event_id) \
            .eq("profile_id", profile_id) \
            .order("updated_at", desc=True) \
            .limit(1) \
            .execute_async()
    if (not existing.data) and stable_platform_id:
        existing = await supabase.table("calendar_event_detections") \
            .select(select_fields) \
            .eq("platform_id", stable_platform_id) \
            .eq("profile_id", profile_id) \
            .order("updated_at", desc=True) \
            .limit(1) \
            .execute_async()
    if (not existing.data) and stable_platform_id:
        existing = await supabase.table("calendar_event_detections") \
            .select(select_fields) \
            .eq("platform_event_id", stable_platform_id) \
            .eq("profile_id", profile_id) \
            .order("updated_at", desc=True) \
            .limit(1) \
            .execute_async()
    if (not existing.data) and stable_ical_uid:
        existing = await supabase.table("calendar_event_detections") \
            .select(select_fields) \
            .eq("ical_uid", stable_ical_uid) \
            .eq("profile_id", profile_id) \
            .order("updated_at", desc=True) \
            .limit(1) \
            .execute_async()
    if (not existing.data) and identity_compound_key:
        existing = await supabase.table("calendar_event_detections") \
            .select(select_fields) \
            .eq("detection_signals->>_identity_key", identity_compound_key) \
            .eq("profile_id", profile_id) \
            .order("updated_at", desc=True) \
            .limit(1) \
            .execute_async()

    if existing.data:
        row = existing.data[0]
        now_iso = datetime.now(timezone.utc).isoformat()
        notification_signature = _notification_signature(event, org_domain)

        identity_patch = {}
        if str(row.get("recall_event_id") or "") != recall_event_id:
            identity_patch["recall_event_id"] = recall_event_id
        if stable_platform_id and str(row.get("platform_id") or "") != stable_platform_id:
            identity_patch["platform_id"] = stable_platform_id
        if stable_platform_id and str(row.get("platform_event_id") or "") != stable_platform_id:
            identity_patch["platform_event_id"] = stable_platform_id
        if stable_ical_uid and str(row.get("ical_uid") or "") != stable_ical_uid:
            identity_patch["ical_uid"] = stable_ical_uid
        if str(row.get("identity_source") or "") != identity_source:
            identity_patch["identity_source"] = identity_source
        if str(row.get("identity_base_key") or "") != identity_base_key:
            identity_patch["identity_base_key"] = identity_base_key
        if str(row.get("identity_instance_key") or "") != identity_instance_key:
            identity_patch["identity_instance_key"] = identity_instance_key or None
        if str(row.get("identity_key") or "") != identity_compound_key:
            identity_patch["identity_key"] = identity_compound_key
        existing_signals = row.get("detection_signals") or {}
        if not isinstance(existing_signals, dict):
            existing_signals = {}
        next_signals = dict(existing_signals)
        next_signals["_identity_source"] = identity_source
        next_signals["_identity_base_key"] = identity_base_key
        if identity_instance_key:
            next_signals["_identity_instance_key"] = identity_instance_key
        else:
            next_signals.pop("_identity_instance_key", None)
        next_signals["_identity_key"] = identity_compound_key
        if next_signals != existing_signals:
            identity_patch["detection_signals"] = next_signals
        if identity_patch:
            identity_patch["updated_at"] = now_iso
            try:
                await supabase.table("calendar_event_detections") \
                    .update(identity_patch) \
                    .eq("id", row["id"]) \
                    .execute_async()
            except Exception as identity_err:
                if not _is_missing_identity_column_error(identity_err):
                    raise
                legacy_patch = {
                    k: v for k, v in identity_patch.items()
                    if k not in {"identity_source", "identity_base_key", "identity_instance_key", "identity_key"}
                }
                if legacy_patch:
                    await supabase.table("calendar_event_detections") \
                        .update(legacy_patch) \
                        .eq("id", row["id"]) \
                        .execute_async()

        if raw.get("status") == "cancelled" or event.get("is_deleted") is True:
            await _check_reschedule(row, event, supabase, org_domain)
            return "processed"

        if _event_has_ended(event, fallback_event_end=row.get("event_end")):
            current_status = str(row.get("detection_status") or "")
            expirable_statuses = {
                "detected",
                "notified",
                "awaiting_role",
                "awaiting_round",
                "awaiting_confirm",
                "orphan_no_response",
                "orphan_role",
                "orphan_round",
                "orphan_confirm",
            }
            if current_status in expirable_statuses:
                await supabase.table("calendar_event_detections") \
                    .update({
                        "detection_status": "expired",
                        "updated_at": now_iso,
                    }) \
                    .eq("id", row["id"]) \
                    .eq("detection_status", current_status) \
                    .execute_async()
            logger.info(
                "Calendar Intelligence: skipping ended existing event "
                f"detection={row['id']} event_id={recall_event_id}"
            )
            return "drop"

        flags = _change_flags(row, event, org_domain)
        reprocessable_statuses = {
            "detected",
            "notified",
            "orphan_no_response",
            "orphan_role",
            "orphan_round",
            "orphan_confirm",
        }
        needs_first_notify = row["detection_status"] == "detected" and not row.get("slack_message_ts")
        should_send_change, change_reason = _should_send_coalesced_change(
            row, flags, datetime.now(timezone.utc)
        )
        needs_reprocess = row["detection_status"] in reprocessable_statuses and should_send_change

        if flags.get("title") or flags.get("time") or flags.get("meeting_url"):
            patch = {"updated_at": now_iso}
            new_title = str(raw.get("summary") or "").strip()
            if new_title:
                patch["event_title"] = new_title
            new_start = _safe_parse_datetime(raw.get("start", {}).get("dateTime"))
            if new_start:
                patch["event_start"] = new_start.isoformat()
            new_end = _safe_parse_datetime(raw.get("end", {}).get("dateTime"))
            if new_end:
                patch["event_end"] = new_end.isoformat()
            new_meeting_url = _extract_meeting_url_for_signature(event)
            if new_meeting_url:
                patch["meeting_url"] = new_meeting_url
            await supabase.table("calendar_event_detections") \
                .update(patch) \
                .eq("id", row["id"]) \
                .execute_async()

        if needs_reprocess or needs_first_notify:
            det_full = await supabase.table("calendar_event_detections") \
                .select("*") \
                .eq("id", row["id"]) \
                .execute_async()
            if det_full.data:
                reqs_result = await supabase.table("requisitions") \
                    .select("id, role_title, role_location, status, created_at") \
                    .eq("created_by", profile_id) \
                    .in_("status", ["open", "active", "sourcing", "planned"]) \
                    .is_("is_system_template", "false") \
                    .is_("deleted_at", "null") \
                    .order("created_at", desc=True) \
                    .limit(MAX_REQS_PER_EVENT) \
                    .execute_async()
                requisitions = reqs_result.data or []
                requisitions_truncated = len(requisitions) >= MAX_REQS_PER_EVENT

                candidates = []
                if requisitions:
                    rounds_result = await supabase.table("rounds") \
                        .select("id, name, requisition_id, duration_minutes") \
                        .in_("requisition_id", [r["id"] for r in requisitions]) \
                        .is_("deleted_at", "null") \
                        .execute_async()
                    for rd in (rounds_result.data or []):
                        for req in requisitions:
                            if str(req["id"]) == str(rd["requisition_id"]):
                                req.setdefault("rounds", []).append(rd)

                    cand_result = await supabase.table("candidates") \
                        .select("id, email, name, requisition_id") \
                        .in_("requisition_id", [r["id"] for r in requisitions]) \
                        .is_("deleted_at", "null") \
                        .execute_async()
                    candidates = cand_result.data or []

                analyzed = analyze_event(event, org_domain)
                if analyzed and requisitions:
                    classification = await llm_classify_and_extract(analyzed)
                    extracted_fields = classification
                    req_matches, match_metadata = await resolve_role_matches(
                        analyzed,
                        requisitions,
                        candidates,
                        extracted_fields,
                        requisitions_truncated=requisitions_truncated,
                    )
                    logger.info(
                        "Calendar Intelligence: role_match "
                        f"detection={row['id']} type={match_metadata.get('match_type')} "
                        f"top_score={match_metadata.get('top_score')} "
                        f"filter={match_metadata.get('filters')} "
                        f"score_ids={list((match_metadata.get('scores') or {}).keys())[:5]}"
                    )
                    if not req_matches:
                        req_matches = requisitions

                    existing_signals = (det_full.data[0].get("detection_signals") or {}) if det_full.data else {}
                    if not isinstance(existing_signals, dict):
                        existing_signals = {}
                    updated_signals = {
                        **existing_signals,
                        "classification": classification,
                        "_role_match": match_metadata,
                        "_identity_source": identity_source,
                        "_identity_base_key": identity_base_key,
                        "_identity_key": identity_compound_key,
                    }
                    if identity_instance_key:
                        updated_signals["_identity_instance_key"] = identity_instance_key
                    else:
                        updated_signals.pop("_identity_instance_key", None)
                    if analyzed.get("event_timezone"):
                        updated_signals["_event_timezone"] = analyzed.get("event_timezone")
                    if profile_timezone:
                        updated_signals["_display_timezone"] = profile_timezone
                    refreshed_detection = dict(det_full.data[0]) if det_full.data else {}
                    refreshed_detection["detection_signals"] = updated_signals
                    refreshed_detection["detection_status"] = row.get("detection_status", refreshed_detection.get("detection_status"))
                    updated_signals = merge_interaction_context(
                        updated_signals,
                        refreshed_detection,
                        current_step="detected",
                    )
                    update_data = {"detection_signals": updated_signals}
                    if classification and classification.get("confidence"):
                        update_data["detection_confidence"] = classification["confidence"]
                    await supabase.table("calendar_event_detections") \
                        .update(update_data) \
                        .eq("id", row["id"]) \
                        .execute_async()
                else:
                    req_matches = requisitions
                    match_metadata = None

                from app.services.slack_service import get_slack_service
                slack_conn = await supabase.table("slack_connections") \
                    .select("slack_user_id, slack_team_id") \
                    .eq("profile_id", profile_id) \
                    .eq("is_active", True) \
                    .execute_async()
                if slack_conn.data:
                    svc = get_slack_service()
                    try:
                        token = await svc.get_bot_token_for_team(slack_conn.data[0]["slack_team_id"])
                        detection_data = det_full.data[0]
                        await _send_slack_notification_with_token(
                            detection_data,
                            req_matches,
                            match_metadata,
                            supabase,
                            svc,
                            token,
                            slack_conn.data[0]["slack_user_id"],
                            team_id=slack_conn.data[0]["slack_team_id"],
                            notification_signature=notification_signature,
                            change_reason=("initial_notify" if needs_first_notify else change_reason),
                            is_initial_notify=needs_first_notify,
                        )
                        if flags.get("title"):
                            logger.info(
                                "Calendar Intelligence: re-sent notification with updated title "
                                f"for detection={row['id']}"
                            )
                    except ValueError:
                        pass
        else:
            await _check_reschedule(row, event, supabase, org_domain)
        return "processed"

    if event.get("bots"):
        # Bot already associated with this event outside of our pipeline —
        # intentional no-op.
        return "processed"

    raw_check = event.get("raw", {})
    if raw_check.get("status") == "cancelled" or event.get("is_deleted") is True:
        # Cancelled / deleted event with no existing detection — nothing to
        # do. Permanent drop (replays won't find a row to clean up either).
        return "drop"

    analyzed = analyze_event(event, org_domain)
    if not analyzed:
        # Not a recognizable calendar event shape — permanent drop.
        return "drop"

    if _event_has_ended(event, fallback_event_end=analyzed.get("event_end")):
        logger.info(
            "Calendar Intelligence: skipping ended new event "
            f"event_id={recall_event_id}"
        )
        return "drop"


    classification = await llm_classify_and_extract(analyzed)
    if classification is None:
        raise RuntimeError("LLM classification failed — event will retry on next poll")

    logger.info(f"Calendar Intelligence: classification={classification}")

    if not classification.get("is_interview") or classification.get("confidence", 0) < 0.5:
        # Not an interview — permanent drop.
        return "drop"

    score = classification.get("confidence", 0)
    signals = {"classification": classification}
    signals["_identity_source"] = identity_source
    signals["_identity_base_key"] = identity_base_key
    signals["_identity_key"] = identity_compound_key
    if identity_instance_key:
        signals["_identity_instance_key"] = identity_instance_key
    if analyzed.get("event_timezone"):
        signals["_event_timezone"] = analyzed.get("event_timezone")
    if profile_timezone:
        signals["_display_timezone"] = profile_timezone
    confidence = "HIGH" if score > 0.8 else "MEDIUM"
    extracted_fields = classification

    org_result = await supabase.table("organizations") \
        .select("auto_join_enabled, auto_join_untracked, blocked_domains, slack_features") \
        .eq("id", org_id) \
        .execute_async()
    org_data = org_result.data[0] if org_result.data else {}
    user_auto_join_untracked = user_info.get("auto_join_untracked")
    if user_auto_join_untracked is None:
        auto_join_untracked_enabled = bool(org_data.get("auto_join_untracked", False))
        auto_join_untracked_source = "organization_fallback"
    else:
        auto_join_untracked_enabled = bool(user_auto_join_untracked)
        auto_join_untracked_source = "user_connection"

    org_slack_features = org_data.get("slack_features") or {}
    user_conn_result = await supabase.table("slack_connections") \
        .select("user_slack_features") \
        .eq("profile_id", profile_id) \
        .eq("is_active", True) \
        .limit(1) \
        .execute_async()
    user_slack_features = (user_conn_result.data[0].get("user_slack_features") or {}) if user_conn_result.data else {}
    effective_features = {**org_slack_features, **user_slack_features}

    if not effective_features.get("calendar_notifications", True):
        logger.info(f"Calendar Intelligence: calendar_notifications disabled for profile={profile_id}, skipping")
        # Feature flag is user/org-scoped config, not transient state. A flip
        # back on is a new event upstream, not a DLQ replay concern. Drop.
        return "drop"

    blocked_domains = org_data.get("blocked_domains") or []
    if blocked_domains:
        blocked_set = {d.lower() for d in blocked_domains}
        for att in analyzed.get("external_attendees", []):
            email = att.get("email", "")
            att_domain = email.split("@")[-1].lower() if "@" in email else ""
            if att_domain in blocked_set:
                logger.info(f"Calendar Intelligence: blocked attendee domain {att_domain} in event, skipping")
                # Blocklist decision is durable org policy; the attendee set
                # of a stored snapshot won't change on replay. Drop.
                return "drop"

    reqs_result = await supabase.table("requisitions") \
        .select("id, role_title, role_location, status, created_at") \
        .eq("created_by", profile_id) \
        .in_("status", ["open", "active", "sourcing", "planned"]) \
        .is_("is_system_template", "false") \
        .is_("deleted_at", "null") \
        .order("created_at", desc=True) \
        .limit(MAX_REQS_PER_EVENT) \
        .execute_async()
    requisitions = reqs_result.data or []
    # Codex Round 3: cap hit → true role may be outside the visible subset,
    # force manual role selection downstream by signalling truncation.
    requisitions_truncated = len(requisitions) >= MAX_REQS_PER_EVENT

    no_req_reason = None
    if not requisitions:
        no_req_reason = "no_reqs"
    else:
        rounds_result = await supabase.table("rounds") \
            .select("id, name, requisition_id, duration_minutes, default_interviewer_emails") \
            .in_("requisition_id", [r["id"] for r in requisitions]) \
            .is_("deleted_at", "null") \
            .execute_async()
        rounds_by_req = {}
        for rd in (rounds_result.data or []):
            req_id = rd["requisition_id"]
            rounds_by_req.setdefault(req_id, []).append(rd)

        for req in requisitions:
            req["rounds"] = rounds_by_req.get(str(req["id"]), [])

        has_plan = any(req["rounds"] for req in requisitions)
        if not has_plan:
            no_req_reason = "no_rounds"

    candidates = []
    if not no_req_reason:
        candidates_result = await supabase.table("candidates") \
            .select("id, email, name, requisition_id") \
            .in_("requisition_id", [r["id"] for r in requisitions]) \
            .is_("deleted_at", "null") \
            .execute_async()
        candidates = candidates_result.data or []

    detection_row = {
        "profile_id": profile_id,
        "organization_id": org_id,
        "recall_calendar_id": str(calendar_id),
        "recall_event_id": recall_event_id,
        "platform_event_id": stable_platform_id or analyzed.get("platform_event_id"),
        "platform_id": stable_platform_id or analyzed.get("platform_id"),
        "ical_uid": stable_ical_uid or analyzed.get("ical_uid"),
        "identity_source": identity_source,
        "identity_base_key": identity_base_key,
        "identity_instance_key": identity_instance_key or None,
        "identity_key": identity_compound_key,
        "event_title": analyzed.get("event_title"),
        "event_start": analyzed["event_start"].isoformat(),
        "event_end": analyzed["event_end"].isoformat(),
        "meeting_url": analyzed.get("meeting_url"),
        "meeting_platform": analyzed.get("meeting_platform"),
        "external_attendees": analyzed.get("external_attendees", []),
        "internal_attendees": analyzed.get("internal_attendees", []),
        "detection_status": "detected",
        "detection_confidence": score,
        "detection_signals": signals,
    }

    org_existing = None
    if identity_compound_key:
        try:
            org_existing = await supabase.table("calendar_event_detections") \
                .select("id") \
                .eq("identity_key", identity_compound_key) \
                .eq("organization_id", org_id) \
                .execute_async()
        except Exception as identity_err:
            if not _is_missing_identity_column_error(identity_err):
                raise
    if not org_existing or not org_existing.data:
        org_existing = await supabase.table("calendar_event_detections") \
            .select("id") \
            .eq("recall_event_id", recall_event_id) \
            .eq("organization_id", org_id) \
            .execute_async()
    if (not org_existing.data) and stable_platform_id:
        org_existing = await supabase.table("calendar_event_detections") \
            .select("id") \
            .eq("platform_id", stable_platform_id) \
            .eq("organization_id", org_id) \
            .execute_async()
    if (not org_existing.data) and stable_platform_id:
        org_existing = await supabase.table("calendar_event_detections") \
            .select("id") \
            .eq("platform_event_id", stable_platform_id) \
            .eq("organization_id", org_id) \
            .execute_async()
    if (not org_existing.data) and stable_ical_uid:
        org_existing = await supabase.table("calendar_event_detections") \
            .select("id") \
            .eq("ical_uid", stable_ical_uid) \
            .eq("organization_id", org_id) \
            .execute_async()
    if (not org_existing.data) and identity_compound_key:
        org_existing = await supabase.table("calendar_event_detections") \
            .select("id") \
            .eq("detection_signals->>_identity_key", identity_compound_key) \
            .eq("organization_id", org_id) \
            .execute_async()
    if org_existing.data:
        logger.debug(f"Calendar Intelligence: detection already exists for event={recall_event_id} in org={org_id}, skipping")
        # A detection row for this event already exists in the org (another
        # user in the org got there first). Intentional no-op, processed.
        return "processed"

    try:
        insert_result = await supabase.table("calendar_event_detections") \
            .insert(detection_row) \
            .execute_async()
    except Exception as e:
        if _is_missing_identity_column_error(e):
            legacy_detection_row = {
                k: v for k, v in detection_row.items()
                if k not in {"identity_source", "identity_base_key", "identity_instance_key", "identity_key"}
            }
            insert_result = await supabase.table("calendar_event_detections") \
                .insert(legacy_detection_row) \
                .execute_async()
        elif "duplicate key" in str(e).lower() or "unique" in str(e).lower():
            logger.debug(f"Calendar Intelligence: duplicate detection for event={recall_event_id}, skipping")
            # Unique-constraint hit — another worker/user inserted the same
            # detection concurrently. Treat as already-processed.
            return "processed"
        else:
            raise

    if not insert_result.data:
        # Insert returned an empty result set without raising. This is an
        # unexpected Supabase client state; don't silently drop the event —
        # defer it so the next drain retries and a real error surfaces.
        logger.warning(
            f"Calendar Intelligence: deferring event={recall_event_id} — "
            f"insert returned empty result for profile={profile_id}"
        )
        return "defer"

    detection = insert_result.data[0] if isinstance(insert_result.data, list) else insert_result.data
    detection_id = detection["id"]

    if no_req_reason:
        from app.services.slack_service import get_slack_service

        capture_result = None
        auto_capture_enabled = (
            is_untracked_capture_enabled()
            and auto_join_untracked_enabled
        )
        if is_untracked_capture_enabled() and not auto_join_untracked_enabled:
            logger.info(
                "Calendar Intelligence: skipping no-req auto-capture for detection=%s source=%s",
                detection_id,
                auto_join_untracked_source,
            )
        if auto_capture_enabled:
            try:
                from app.services.calendar_intelligence_handler import _link_bot_to_candidate_round

                capture_result = await capture_untracked_interview(
                    supabase,
                    detection,
                    _link_bot_to_candidate_round,
                )
            except Exception as capture_exc:
                logger.error(
                    f"Calendar Intelligence: untracked auto-capture failed for detection={detection_id}: {capture_exc}",
                    exc_info=True,
                )

        slack_conn = await supabase.table("slack_connections") \
            .select("slack_user_id, slack_team_id") \
            .eq("profile_id", profile_id) \
            .eq("is_active", True) \
            .execute_async()
        if slack_conn.data:
            service = get_slack_service()
            try:
                bot_token = await service.get_bot_token_for_team(slack_conn.data[0]["slack_team_id"])
                if capture_result:
                    blocks = build_untracked_captured_blocks(
                        detection,
                        candidate_name=capture_result.candidate_name,
                        candidate_email=capture_result.candidate_email,
                    )
                    notification_text = "Interview captured"
                else:
                    blocks = build_no_req_blocks(detection, no_req_reason)
                    notification_text = "Interview detected — no matching role found"
                result = await service.send_dm(
                    bot_token=bot_token,
                    slack_user_id=slack_conn.data[0]["slack_user_id"],
                    text=notification_text,
                    blocks=blocks,
                    team_id=slack_conn.data[0]["slack_team_id"],
                )
                if result and result.get("ok"):
                    now = datetime.now(timezone.utc).isoformat()
                    update_payload = {
                        "slack_channel_id": result.get("channel"),
                        "slack_message_ts": result.get("ts"),
                        "notified_at": now,
                        "updated_at": now,
                    }
                    if not capture_result:
                        update_payload["detection_status"] = "notified"

                    update_query = supabase.table("calendar_event_detections") \
                        .update(update_payload) \
                        .eq("id", detection_id)
                    if not capture_result:
                        update_query = update_query.eq("detection_status", "detected")
                    await update_query.execute_async()

                    if capture_result:
                        logger.info(
                            f"Calendar Intelligence: untracked capture notification sent for detection={detection_id}"
                        )
                    else:
                        logger.info(
                            f"Calendar Intelligence: no-req notification sent for detection={detection_id} reason={no_req_reason}"
                        )
            except ValueError:
                logger.warning(f"Calendar Intelligence: no bot token for no-req notification")
        else:
            logger.info(f"Calendar Intelligence: no Slack for no-req notification profile={profile_id}")
        # Detection row is inserted and the no-req notification path is
        # terminal — handled fully, even if Slack is unreachable.
        return "processed"

    deployed_bot_id = None
    precapture_result = None
    auto_join = org_data.get("auto_join_enabled", True) and confidence in ("HIGH", "MEDIUM")
    auto_untracked_precapture = (
        auto_join
        and auto_join_untracked_enabled
        and is_untracked_capture_enabled()
    )
    if auto_join and is_untracked_capture_enabled() and not auto_join_untracked_enabled:
        logger.info(
            "Calendar Intelligence: skipping pre-capture for detection=%s source=%s",
            detection_id,
            auto_join_untracked_source,
        )
    if auto_join:
        existing_bot_for_event = None
        if identity_compound_key:
            try:
                existing_bot_for_event = await supabase.table("calendar_event_detections") \
                    .select("id") \
                    .eq("identity_key", identity_compound_key) \
                    .eq("organization_id", org_id) \
                    .neq("id", detection_id) \
                    .execute_async()
            except Exception as identity_err:
                if not _is_missing_identity_column_error(identity_err):
                    raise
        if not existing_bot_for_event or not existing_bot_for_event.data:
            existing_bot_for_event = await supabase.table("calendar_event_detections") \
                .select("id") \
                .eq("recall_event_id", recall_event_id) \
                .eq("organization_id", org_id) \
                .neq("id", detection_id) \
                .execute_async()
        if (not existing_bot_for_event.data) and stable_platform_id:
            existing_bot_for_event = await supabase.table("calendar_event_detections") \
                .select("id") \
                .eq("platform_id", stable_platform_id) \
                .eq("organization_id", org_id) \
                .neq("id", detection_id) \
                .execute_async()
        if (not existing_bot_for_event.data) and stable_platform_id:
            existing_bot_for_event = await supabase.table("calendar_event_detections") \
                .select("id") \
                .eq("platform_event_id", stable_platform_id) \
                .eq("organization_id", org_id) \
                .neq("id", detection_id) \
                .execute_async()
        if (not existing_bot_for_event.data) and stable_ical_uid:
            existing_bot_for_event = await supabase.table("calendar_event_detections") \
                .select("id") \
                .eq("ical_uid", stable_ical_uid) \
                .eq("organization_id", org_id) \
                .neq("id", detection_id) \
                .execute_async()
        if (not existing_bot_for_event.data) and identity_compound_key:
            existing_bot_for_event = await supabase.table("calendar_event_detections") \
                .select("id") \
                .eq("detection_signals->>_identity_key", identity_compound_key) \
                .eq("organization_id", org_id) \
                .neq("id", detection_id) \
                .execute_async()
        if existing_bot_for_event.data:
            logger.info(f"Calendar Intelligence: bot already deployed for event={recall_event_id} by another user in org, skipping auto-join")
            auto_join = False

    if auto_join and auto_untracked_precapture:
        try:
            from app.services.calendar_intelligence_handler import _link_bot_to_candidate_round

            precapture_result = await materialize_untracked_capture(
                supabase=supabase,
                detection=detection,
                bot_linker=_link_bot_to_candidate_round,
                capture_mode="preconfirm",
                finalize_detection=False,
            )
            if precapture_result:
                latest_detection_bot = await supabase.table("recall_bots") \
                    .select("recall_bot_id") \
                    .eq("detection_id", str(detection_id)) \
                    .eq("candidate_round_id", precapture_result.candidate_round_id) \
                    .in_("status", _DETECTION_BOT_ATTACHABLE_STATUSES) \
                    .order("created_at", desc=True) \
                    .limit(1) \
                    .execute_async()
                if latest_detection_bot.data:
                    deployed_bot_id = str(latest_detection_bot.data[0].get("recall_bot_id") or "")
                logger.info(
                    "Calendar Intelligence: pre-confirm untracked capture materialized "
                    f"detection={detection_id} candidate_round_id={precapture_result.candidate_round_id}"
                )
            else:
                logger.warning(
                    "Calendar Intelligence: pre-confirm untracked capture failed "
                    f"detection={detection_id}; skipping auto-join"
                )
        except Exception as capture_exc:
            logger.error(
                f"Calendar Intelligence: pre-confirm untracked capture failed for detection={detection_id}: {capture_exc}",
                exc_info=True,
            )
    elif auto_join:
        external = analyzed.get("external_attendees") or []
        candidate_name = external[0].get("display_name", "Candidate") if external else "Candidate"
        deployed_bot_id = await _schedule_detection_voice_bot(
            supabase=supabase,
            detection_id=str(detection_id),
            meeting_url=str(analyzed.get("meeting_url") or ""),
            event_start=analyzed.get("event_start"),
            candidate_name=candidate_name,
        )
        if deployed_bot_id:
            logger.info(f"Calendar Intelligence: auto-join bot deployed for detection={detection_id}")

    req_matches, match_metadata = await resolve_role_matches(
        analyzed,
        requisitions,
        candidates,
        extracted_fields,
        requisitions_truncated=requisitions_truncated,
    )
    logger.info(
        "Calendar Intelligence: role_match "
        f"detection={detection_id} type={match_metadata.get('match_type')} "
        f"top_score={match_metadata.get('top_score')} "
        f"filter={match_metadata.get('filters')} "
        f"score_ids={list((match_metadata.get('scores') or {}).keys())[:5]}"
    )
    if not req_matches:
        req_matches = requisitions

    latest_signals = signals
    if precapture_result:
        latest_detection = await supabase.table("calendar_event_detections") \
            .select("detection_signals") \
            .eq("id", detection_id) \
            .limit(1) \
            .execute_async()
        if latest_detection.data:
            fetched = latest_detection.data[0].get("detection_signals")
            if isinstance(fetched, dict):
                latest_signals = fetched
    if not isinstance(latest_signals, dict):
        latest_signals = {}

    latest_signals["_role_match"] = match_metadata
    context_detection = dict(detection)
    context_detection["detection_signals"] = latest_signals
    signals = merge_interaction_context(
        latest_signals,
        context_detection,
        current_step="detected",
    )
    await supabase.table("calendar_event_detections") \
        .update({"detection_signals": signals}) \
        .eq("id", detection_id) \
        .execute_async()

    from app.services.slack_service import get_slack_service
    slack_conn = await supabase.table("slack_connections") \
        .select("slack_user_id, slack_team_id") \
        .eq("profile_id", profile_id) \
        .eq("is_active", True) \
        .execute_async()

    if not slack_conn.data:
        logger.info(f"Calendar Intelligence: no Slack for profile={profile_id}")
        if deployed_bot_id:
            logger.warning(f"Calendar Intelligence: rolling back bot {deployed_bot_id} — no Slack to notify user")
            try:
                await _rollback_detection_voice_bot(supabase, str(deployed_bot_id))
            except Exception as e:
                logger.error(f"Calendar Intelligence: bot rollback failed: {e}")
        # Detection row is durable in DB; without a Slack connection the user
        # cannot be notified. Re-connecting Slack will be picked up via the
        # detected→notified reprocess path on the next event change, not via
        # DLQ replay. Treat as a terminal drop for DLQ purposes.
        return "drop"

    service = get_slack_service()
    try:
        bot_token = await service.get_bot_token_for_team(slack_conn.data[0]["slack_team_id"])
    except ValueError:
        logger.warning(f"Calendar Intelligence: no bot token")
        if deployed_bot_id:
            logger.warning(f"Calendar Intelligence: rolling back bot {deployed_bot_id} — no bot token to notify user")
            try:
                await _rollback_detection_voice_bot(supabase, str(deployed_bot_id))
            except Exception as e:
                logger.error(f"Calendar Intelligence: bot rollback failed: {e}")
        # Slack install is broken (missing bot token) — same reasoning as the
        # no-Slack path. Drop for DLQ purposes; operator must reinstall.
        return "drop"

    notify_ok = await _send_slack_notification_with_token(
        detection, req_matches, match_metadata, supabase, service, bot_token,
        slack_conn.data[0]["slack_user_id"],
        team_id=slack_conn.data[0]["slack_team_id"],
        notification_signature=_notification_signature(event, org_domain),
        change_reason="initial_notify",
        is_initial_notify=True,
    )

    if not notify_ok and deployed_bot_id:
        logger.warning(f"Calendar Intelligence: notification failed, rolling back auto-join bot {deployed_bot_id}")
        try:
            await _rollback_detection_voice_bot(supabase, str(deployed_bot_id))
        except Exception as e:
            logger.error(f"Calendar Intelligence: bot rollback failed: {e}")

    # Codex Round 7: explicit terminal outcome so the DLQ drain can remove
    # the entry. Reaching this fall-through means the detection row is
    # inserted and the Slack notification path ran (successfully or not —
    # a failed notification is not retriable at the event level, it is
    # handled by the detected→notified reprocess path on next event change).
    return "processed"


async def _send_slack_notification_with_token(
    detection: dict, req_matches: list[dict], match_metadata,
    supabase, service, bot_token: str, slack_user_id: str,
    team_id: str | None = None,
    notification_signature: str = "",
    change_reason: str = "",
    is_initial_notify: bool = False,
) -> bool:
    detection_id = str(detection["id"])

    blocks = build_detection_blocks(detection, req_matches, match_metadata)
    existing_channel = str(detection.get("slack_channel_id") or "").strip()
    existing_ts = str(detection.get("slack_message_ts") or "").strip()
    using_existing_message = bool(existing_channel and existing_ts)
    if using_existing_message:
        result = await service.update_message(
            bot_token=bot_token,
            channel=existing_channel,
            ts=existing_ts,
            text="Interview detected on your calendar",
            blocks=blocks,
            team_id=team_id,
        )
    else:
        result = await service.send_dm(
            bot_token=bot_token,
            slack_user_id=slack_user_id,
            text="Interview detected on your calendar",
            blocks=blocks,
            team_id=team_id,
        )

    if result and result.get("ok"):
        channel = result.get("channel") or existing_channel
        ts = result.get("ts") or existing_ts
        now = datetime.now(timezone.utc).isoformat()
        next_signals = {}
        latest_row = await supabase.table("calendar_event_detections") \
            .select("detection_signals") \
            .eq("id", detection_id) \
            .limit(1) \
            .execute_async()
        if latest_row.data:
            next_signals = latest_row.data[0].get("detection_signals") or {}
        if not next_signals:
            next_signals = detection.get("detection_signals") or {}
        if not isinstance(next_signals, dict):
            next_signals = {}
        if isinstance(match_metadata, dict):
            next_signals["_role_match"] = match_metadata
        ui_state = next_signals.get("_ui_state") or {}
        if not isinstance(ui_state, dict):
            ui_state = {}
        ui_state.setdefault("current_step", "role_select")
        ui_state.setdefault("state_stack", [])
        if not ui_state.get("role_candidates") and req_matches:
            ui_state["role_candidates"] = [
                {
                    "id": str(r.get("id")),
                    "role_title": r.get("role_title", "Unknown"),
                    "role_location": r.get("role_location", ""),
                    "status": r.get("status", ""),
                    "created_at": r.get("created_at", ""),
                }
                for r in req_matches[:25] if r.get("id")
            ]
        next_signals["_ui_state"] = ui_state
        context_detection = dict(detection)
        context_detection["detection_signals"] = next_signals
        context_detection["detection_status"] = "notified"
        next_signals = merge_interaction_context(
            next_signals,
            context_detection,
            role_title=str(ui_state.get("role_title") or ""),
            current_step="role_select",
        )
        update_payload = {
            "detection_status": "notified",
            "detection_signals": next_signals,
            "notified_at": now,
            "updated_at": now,
            "reminder_policy_version": "single_t_minus_2h_v1",
        }
        if channel:
            update_payload["slack_channel_id"] = channel
        if ts:
            update_payload["slack_message_ts"] = ts
        if notification_signature:
            update_payload["last_notified_signature"] = notification_signature
        if change_reason and change_reason != "initial_notify":
            update_payload["last_change_notified_at"] = now
        if is_initial_notify and _should_mark_initial_notify_as_reminded(detection.get("event_start")):
            update_payload["reminder_count"] = 1
            update_payload["last_reminded_at"] = now
            update_payload["last_reminded_reason"] = "at_detection_inside_window"

        cas_result = await supabase.table("calendar_event_detections") \
            .update(update_payload) \
            .eq("id", detection_id) \
            .in_("detection_status", [
                "detected",
                "notified",
                "orphan_no_response",
                "orphan_role",
                "orphan_round",
                "orphan_confirm",
            ]) \
            .execute_async()
        if not cas_result.data:
            logger.warning(f"Calendar Intelligence: CAS failed for notification update detection={detection_id} — status already advanced")
            return True
        if using_existing_message:
            logger.info(f"Calendar Intelligence: notification updated for detection={detection_id}")
        else:
            logger.info(f"Calendar Intelligence: notification sent for detection={detection_id}")
        return True
    else:
        if using_existing_message:
            logger.warning(f"Calendar Intelligence: Slack update failed for detection={detection_id}: {result}")
        else:
            logger.warning(f"Calendar Intelligence: Slack DM failed for detection={detection_id}: {result}")
        return False


async def _check_reschedule(existing: dict, event: dict, supabase, org_domain: str = ""):
    raw = event.get("raw", {})

    is_cancelled = raw.get("status") == "cancelled" or event.get("is_deleted") is True
    if is_cancelled:
        detection_id = existing["id"]
        current_status = existing["detection_status"]
        now_iso = datetime.now(timezone.utc).isoformat()

        if current_status == "confirmed":
            det_full = await supabase.table("calendar_event_detections") \
                .select("matched_candidate_round_id, profile_id") \
                .eq("id", detection_id) \
                .execute_async()
            det_data = det_full.data[0] if det_full.data else {}

            cr_id = det_data.get("matched_candidate_round_id")
            if cr_id:
                cr_row = await supabase.table("candidate_rounds") \
                    .select("id, status, scheduled_at") \
                    .eq("id", cr_id) \
                    .execute_async()
                if cr_row.data:
                    cr_status = cr_row.data[0].get("status")
                    if cr_status in ("pending", "scheduled"):
                        await supabase.table("candidate_rounds") \
                            .update({"status": "cancelled", "updated_at": now_iso}) \
                            .eq("id", cr_id) \
                            .eq("status", cr_status) \
                            .execute_async()
                    else:
                        logger.info(f"Calendar Intelligence: cancel skipped cr={cr_id} status={cr_status} (already progressed)")

            bot_rows = await supabase.table("recall_bots") \
                .select("id, recall_bot_id, status") \
                .eq("detection_id", detection_id) \
                .execute_async()
            bot_cancel_ok = True
            bot_data = bot_rows.data or []
            recall = None
            if bot_data:
                from app.services.recall_service import get_recall_service
                recall = get_recall_service()
            try:
                for bot in bot_data:
                    try:
                        if bot.get("status") in ("in_call_recording", "in_call_not_recording"):
                            await recall.remove_bot_from_call(bot["recall_bot_id"])
                        elif bot.get("status") in ("created", "joining", "in_waiting_room"):
                            await recall.delete_bot(bot["recall_bot_id"])
                    except Exception as e:
                        bot_cancel_ok = False
                        logger.warning(f"Calendar Intelligence: cancel bot on event deletion failed: {e}")
            finally:
                if recall is not None:
                    try:
                        await recall.close()
                    except Exception as close_err:
                        logger.warning(f"Calendar Intelligence: recall client close failed: {close_err}")

            if not bot_cancel_ok:
                logger.error(f"Calendar Intelligence: event cancelled but bot cancel failed for detection={detection_id}, not dismissing")
            else:
                await supabase.table("calendar_event_detections") \
                    .update({"detection_status": "dismissed", "updated_at": now_iso}) \
                    .eq("id", detection_id) \
                    .eq("detection_status", "confirmed") \
                    .execute_async()

            slack_conn = await supabase.table("slack_connections") \
                .select("slack_user_id, slack_team_id") \
                .eq("profile_id", det_data.get("profile_id")) \
                .eq("is_active", True) \
                .execute_async()
            if slack_conn.data:
                try:
                    from app.services.slack_service import get_slack_service
                    service = get_slack_service()
                    bot_token = await service.get_bot_token_for_team(slack_conn.data[0]["slack_team_id"])
                    await service.send_dm(
                        bot_token=bot_token,
                        slack_user_id=slack_conn.data[0]["slack_user_id"],
                        text="Meeting cancelled",
                        blocks=[{"type": "section", "block_id": "cal_intel_cancelled",
                                 "text": {"type": "mrkdwn", "text": ":x: *Meeting cancelled* — bot stopped, interview removed from OpenRecruiting"}}],
                        team_id=slack_conn.data[0]["slack_team_id"],
                    )
                except Exception as e:
                    logger.warning(f"Calendar Intelligence: cancellation notification failed: {e}")
        else:
            await supabase.table("calendar_event_detections") \
                .update({"detection_status": "dismissed", "updated_at": now_iso}) \
                .eq("id", detection_id) \
                .eq("detection_status", current_status) \
                .execute_async()
        return

    # --- Attendee diff (runs independently of time changes) ---
    if org_domain:
        try:
            from app.services.calendar_intelligence_service import (
                extract_attendees, resolve_interviewer_email, build_attendee_change_blocks,
            )
            new_ext, new_int = extract_attendees(event, org_domain)

            old_int_emails = {a.get("email", "").lower() for a in (existing.get("internal_attendees") or []) if a.get("email")}
            new_int_emails = {a.get("email", "").lower() for a in new_int if a.get("email")}
            old_ext_emails = {a.get("email", "").lower() for a in (existing.get("external_attendees") or []) if a.get("email")}
            new_ext_emails = {a.get("email", "").lower() for a in new_ext if a.get("email")}

            internal_changed = old_int_emails != new_int_emails
            external_changed = old_ext_emails != new_ext_emails

            if internal_changed or external_changed:
                now_iso = datetime.now(timezone.utc).isoformat()
                detection_id = existing["id"]
                current_status_att = existing["detection_status"]

                # Best-effort interviewer sync for confirmed detections (decoupled from snapshot)
                if current_status_att == "confirmed" and internal_changed:
                    cr_id = existing.get("matched_candidate_round_id")
                    if cr_id:
                        try:
                            user_conn = await supabase.table("user_connections") \
                                .select("provider_email") \
                                .eq("profile_id", existing.get("profile_id", "")) \
                                .eq("provider", "google_calendar") \
                                .eq("is_active", True) \
                                .limit(1) \
                                .execute_async()
                            recruiter_email = user_conn.data[0]["provider_email"] if user_conn.data else ""

                            cr_data = await supabase.table("candidate_rounds") \
                                .select("round_id") \
                                .eq("id", cr_id) \
                                .execute_async()
                            round_data = None
                            if cr_data.data:
                                rd = await supabase.table("rounds") \
                                    .select("id, default_interviewer_emails") \
                                    .eq("id", cr_data.data[0]["round_id"]) \
                                    .execute_async()
                                round_data = rd.data[0] if rd.data else None

                            new_interviewer = resolve_interviewer_email(new_int, round_data, recruiter_email)
                            if new_interviewer:
                                await supabase.table("candidate_rounds") \
                                    .update({"interviewer_email": new_interviewer, "updated_at": now_iso}) \
                                    .eq("id", cr_id) \
                                    .in_("status", ["pending", "scheduled"]) \
                                    .execute_async()
                                logger.info(f"Calendar Intelligence: interviewer email updated to {new_interviewer} for cr={cr_id}")
                        except Exception as e:
                            logger.warning(f"Calendar Intelligence: interviewer sync failed for detection={detection_id}: {e}")

                # Persist attendee snapshot with CAS on status to avoid stale writes
                snapshot_update = {
                    "internal_attendees": new_int,
                    "external_attendees": new_ext,
                    "updated_at": now_iso,
                }
                still_confirmed = False
                if current_status_att == "confirmed":
                    snap_result = await supabase.table("calendar_event_detections") \
                        .update(snapshot_update) \
                        .eq("id", detection_id) \
                        .eq("detection_status", "confirmed") \
                        .execute_async()
                    still_confirmed = bool(snap_result.data)
                    if not still_confirmed:
                        logger.warning(f"Calendar Intelligence: attendee snapshot CAS failed for detection={detection_id} — status changed concurrently, skipping notification")
                else:
                    await supabase.table("calendar_event_detections") \
                        .update(snapshot_update) \
                        .eq("id", detection_id) \
                        .execute_async()
                logger.info(f"Calendar Intelligence: attendee change detected for detection={detection_id}: "
                             f"internal_changed={internal_changed}, external_changed={external_changed}")

                if still_confirmed:
                    try:
                        blocks = build_attendee_change_blocks(
                            {**existing, "internal_attendees": new_int, "external_attendees": new_ext},
                            old_int_emails, new_int_emails, old_ext_emails, new_ext_emails,
                        )
                        from app.services.slack_service import get_slack_service
                        slack_conn = await supabase.table("slack_connections") \
                            .select("slack_user_id, slack_team_id") \
                            .eq("profile_id", existing.get("profile_id", "")) \
                            .eq("is_active", True) \
                            .execute_async()
                        if slack_conn.data:
                            service = get_slack_service()
                            bot_token = await service.get_bot_token_for_team(slack_conn.data[0]["slack_team_id"])
                            await service.send_dm(
                                bot_token=bot_token,
                                slack_user_id=slack_conn.data[0]["slack_user_id"],
                                text="Attendee change detected",
                                blocks=blocks,
                                team_id=slack_conn.data[0]["slack_team_id"],
                            )
                            logger.info(f"Calendar Intelligence: attendee change notification sent for detection={detection_id}")
                    except Exception as e:
                        logger.error(f"Calendar Intelligence: attendee change notification failed: {e}")

        except Exception as e:
            logger.error(f"Calendar Intelligence: attendee diff error for detection={existing.get('id')}: {e}")

    # --- Time change handling ---
    new_start_str = raw.get("start", {}).get("dateTime")
    if not new_start_str:
        return

    try:
        new_start = datetime.fromisoformat(new_start_str)
    except (ValueError, TypeError):
        return

    old_start_str = existing.get("event_start")
    if not old_start_str:
        return

    try:
        old_start = datetime.fromisoformat(old_start_str) if isinstance(old_start_str, str) else old_start_str
    except (ValueError, TypeError):
        return

    if hasattr(old_start, 'tzinfo') and old_start.tzinfo is None:
        old_start = old_start.replace(tzinfo=timezone.utc)
    if hasattr(new_start, 'tzinfo') and new_start.tzinfo is None:
        new_start = new_start.replace(tzinfo=timezone.utc)

    time_diff = abs((new_start - old_start).total_seconds())
    if time_diff < 60:
        return

    detection_id = existing["id"]
    current_status = existing["detection_status"]

    new_end_str = raw.get("end", {}).get("dateTime")

    update_data = {
        "event_start": new_start.isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if new_end_str:
        update_data["event_end"] = new_end_str

    await supabase.table("calendar_event_detections") \
        .update(update_data) \
        .eq("id", detection_id) \
        .execute_async()

    if current_status == "confirmed":
        detection = await supabase.table("calendar_event_detections") \
            .select("*") \
            .eq("id", detection_id) \
            .execute_async()
        if detection.data:
            det = detection.data[0]
            blocks = build_reschedule_blocks(det, old_start, new_start)
            from app.services.slack_service import get_slack_service

            slack_conn = await supabase.table("slack_connections") \
                .select("slack_user_id, slack_team_id") \
                .eq("profile_id", det["profile_id"]) \
                .eq("is_active", True) \
                .execute_async()

            if slack_conn.data:
                service = get_slack_service()
                try:
                    bot_token = await service.get_bot_token_for_team(slack_conn.data[0]["slack_team_id"])
                    await service.send_dm(
                        bot_token=bot_token,
                        slack_user_id=slack_conn.data[0]["slack_user_id"],
                        text="Interview rescheduled",
                        blocks=blocks,
                        team_id=slack_conn.data[0]["slack_team_id"],
                    )
                except Exception as e:
                    logger.error(f"Calendar Intelligence: reschedule notification failed: {e}")


async def _try_acquire_job_lock(job_key: str) -> str | None:
    """Generic CAS lock for cron jobs. Same pattern as poll lock.
    Lock rows are seeded by migration 58-calendar-intelligence.sql."""
    supabase = get_supabase_admin_client()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    lock_result = await supabase.table("calendar_intelligence_state") \
        .update({"value": now_iso, "updated_at": now_iso}) \
        .eq("key", job_key) \
        .is_("value", "null") \
        .execute_async()

    if lock_result.data:
        return now_iso

    row = await supabase.table("calendar_intelligence_state") \
        .select("value") \
        .eq("key", job_key) \
        .execute_async()
    locked_at = row.data[0].get("value") if row.data else None

    if locked_at:
        try:
            locked_time = datetime.fromisoformat(locked_at)
            age = (now - locked_time.astimezone(timezone.utc)).total_seconds()
            if age > POLL_LOCK_STALE_SECONDS:
                lock_result = await supabase.table("calendar_intelligence_state") \
                    .update({"value": now_iso, "updated_at": now_iso}) \
                    .eq("key", job_key) \
                    .eq("value", locked_at) \
                    .execute_async()
                return now_iso if lock_result.data else None
        except (ValueError, TypeError):
            pass

    return None


async def _release_job_lock(job_key: str, token: str):
    supabase = get_supabase_admin_client()
    await supabase.table("calendar_intelligence_state") \
        .update({"value": None, "updated_at": datetime.now(timezone.utc).isoformat()}) \
        .eq("key", job_key) \
        .eq("value", token) \
        .execute_async()


async def process_orphan_reminders():
    settings = get_settings()
    if not settings.CALENDAR_INTELLIGENCE_ENABLED:
        return

    lock_token = await _try_acquire_job_lock("reminder_locked_at")
    if not lock_token:
        return

    try:
        supabase = get_supabase_admin_client()
        now = datetime.now(timezone.utc)

        stale_cutoff = (now - timedelta(minutes=30)).isoformat()
        stale_confirming = await supabase.table("calendar_event_detections") \
            .select("id, matched_candidate_round_id, matched_candidate_id") \
            .eq("detection_status", "confirming") \
            .lt("updated_at", stale_cutoff) \
            .execute_async()
        for row in (stale_confirming.data or []):
            cas = await supabase.table("calendar_event_detections") \
                .update({"detection_status": "notified", "updated_at": now.isoformat()}) \
                .eq("id", row["id"]) \
                .eq("detection_status", "confirming") \
                .execute_async()
            if not cas.data:
                continue
            cr_id = row.get("matched_candidate_round_id")
            if cr_id:
                await supabase.table("candidate_rounds") \
                    .update({"status": "cancelled", "updated_at": now.isoformat()}) \
                    .eq("id", cr_id) \
                    .in_("status", ["pending", "scheduled"]) \
                    .execute_async()
            orphan_bots = await supabase.table("recall_bots") \
                .select("id, recall_bot_id, status") \
                .eq("detection_id", row["id"]) \
                .in_("status", ["created", "joining", "in_waiting_room"]) \
                .execute_async()
            orphan_bot_data = orphan_bots.data or []
            recall = None
            if orphan_bot_data:
                from app.services.recall_service import get_recall_service
                recall = get_recall_service()
            try:
                for bot in orphan_bot_data:
                    try:
                        await recall.delete_bot(bot["recall_bot_id"])
                    except Exception as bot_err:
                        logger.warning(f"Calendar Intelligence: orphan bot cleanup failed for bot={bot['recall_bot_id']}: {bot_err}")
            finally:
                if recall is not None:
                    try:
                        await recall.close()
                    except Exception as close_err:
                        logger.warning(f"Calendar Intelligence: recall client close failed: {close_err}")
            logger.warning(f"Calendar Intelligence: recovered stale confirming detection={row['id']} with side-effect cleanup")

        stale_detected_cutoff = (now - timedelta(minutes=10)).isoformat()
        stale_detected = await supabase.table("calendar_event_detections") \
            .select("id, profile_id") \
            .eq("detection_status", "detected") \
            .lt("created_at", stale_detected_cutoff) \
            .gt("event_start", now.isoformat()) \
            .execute_async()
        for det_row in (stale_detected.data or []):
            try:
                det_full = await supabase.table("calendar_event_detections") \
                    .select("*") \
                    .eq("id", det_row["id"]) \
                    .execute_async()
                if not det_full.data:
                    continue
                reqs = await supabase.table("requisitions") \
                    .select("id, role_title, role_location, status, created_at") \
                    .eq("created_by", det_row["profile_id"]) \
                    .in_("status", ["open", "active", "sourcing", "planned"]) \
                    .is_("is_system_template", "false") \
                    .is_("deleted_at", "null") \
                    .order("created_at", desc=True) \
                    .limit(MAX_REQS_PER_EVENT) \
                    .execute_async()
                from app.services.slack_service import get_slack_service
                s_conn = await supabase.table("slack_connections") \
                    .select("slack_user_id, slack_team_id") \
                    .eq("profile_id", det_row["profile_id"]) \
                    .eq("is_active", True) \
                    .execute_async()
                if s_conn.data:
                    svc = get_slack_service()
                    token = await svc.get_bot_token_for_team(s_conn.data[0]["slack_team_id"])
                    await _send_slack_notification_with_token(
                        det_full.data[0], reqs.data or [], None,
                        supabase, svc, token, s_conn.data[0]["slack_user_id"],
                        team_id=s_conn.data[0]["slack_team_id"],
                        is_initial_notify=True,
                        change_reason="initial_notify",
                    )
            except Exception as e:
                logger.error(f"Calendar Intelligence: stale detected retry failed for {det_row['id']}: {e}")

        orphan_statuses = [
            "notified",
            "orphan_no_response", "orphan_role", "orphan_round", "orphan_confirm",
        ]
        lead_hours = _orphan_reminder_lead_hours()
        # Past orphan detections are no longer actionable; expire them eagerly.
        await supabase.table("calendar_event_detections") \
            .update({
                "detection_status": "expired",
                "updated_at": now.isoformat(),
            }) \
            .in_("detection_status", orphan_statuses) \
            .lt("event_start", now.isoformat()) \
            .execute_async()

        reminder_window_end = (
            now + timedelta(hours=lead_hours)
        ).isoformat()

        result = await supabase.table("calendar_event_detections") \
            .select("*") \
            .in_("detection_status", orphan_statuses) \
            .lt("reminder_count", 1) \
            .gt("event_start", now.isoformat()) \
            .lte("event_start", reminder_window_end) \
            .execute_async()

        detections = result.data or []

        for det in detections:
            try:
                notified_at_str = det.get("notified_at")
                if not notified_at_str:
                    continue
                notified_at = datetime.fromisoformat(notified_at_str)
                if notified_at.tzinfo is None:
                    notified_at = notified_at.replace(tzinfo=timezone.utc)

                event_start = datetime.fromisoformat(det["event_start"])
                if event_start.tzinfo is None:
                    event_start = event_start.replace(tzinfo=timezone.utc)
                if event_start <= now:
                    logger.debug(
                        "Calendar Intelligence: skipping reminder for past event "
                        f"detection={det['id']} event_start={det['event_start']}"
                    )
                    continue

                # If the first detection notification was already sent inside
                # the configured lead window, treat that as the one allowed reminder and
                # suppress a duplicate ping.
                if notified_at >= (event_start - timedelta(hours=lead_hours)):
                    await supabase.table("calendar_event_detections") \
                        .update({
                            "reminder_count": 1,
                            "last_reminded_at": now.isoformat(),
                            "last_reminded_reason": "at_detection_inside_window",
                            "reminder_policy_version": "single_t_minus_2h_v1",
                            "updated_at": now.isoformat(),
                        }) \
                        .eq("id", det["id"]) \
                        .in_("detection_status", orphan_statuses) \
                        .lt("reminder_count", 1) \
                        .execute_async()
                    logger.debug(
                        "Calendar Intelligence: reminder suppressed (late detection) "
                        f"detection={det['id']}"
                    )
                    continue

                fresh = await supabase.table("calendar_event_detections") \
                    .select("detection_status") \
                    .eq("id", det["id"]) \
                    .execute_async()
                if not fresh.data or fresh.data[0]["detection_status"] not in orphan_statuses:
                    continue

                blocks = build_reminder_blocks(det, 1)

                slack_conn = await supabase.table("slack_connections") \
                    .select("slack_user_id, slack_team_id") \
                    .eq("profile_id", det["profile_id"]) \
                    .eq("is_active", True) \
                    .execute_async()

                if slack_conn.data:
                    from app.services.slack_service import get_slack_service
                    service = get_slack_service()
                    try:
                        bot_token = await service.get_bot_token_for_team(slack_conn.data[0]["slack_team_id"])
                        await service.send_dm(
                            bot_token=bot_token,
                            slack_user_id=slack_conn.data[0]["slack_user_id"],
                            text=(
                                f"Upcoming interview in {lead_hours} hour"
                                f"{'' if lead_hours == 1 else 's'}. "
                                "Do you want to get instant feedback with OpenRecruiting?"
                            ),
                            blocks=blocks,
                            team_id=slack_conn.data[0]["slack_team_id"],
                        )
                    except Exception as e:
                        logger.error(f"Calendar Intelligence: reminder send failed for {det['id']}: {e}")
                        continue

                await supabase.table("calendar_event_detections") \
                    .update({
                        "reminder_count": 1,
                        "last_reminded_at": now.isoformat(),
                        "last_reminded_reason": "t_minus_2h",
                        "reminder_policy_version": "single_t_minus_2h_v1",
                        "updated_at": now.isoformat(),
                    }) \
                    .eq("id", det["id"]) \
                    .in_("detection_status", orphan_statuses) \
                    .lt("reminder_count", 1) \
                    .execute_async()

            except Exception as e:
                logger.error(f"Calendar Intelligence: orphan reminder error for {det.get('id')}: {e}")

    except Exception as e:
        logger.error(f"Calendar Intelligence process_orphan_reminders error: {e}", exc_info=True)
    finally:
        await _release_job_lock("reminder_locked_at", lock_token)


async def cleanup_expired_detections():
    settings = get_settings()
    if not settings.CALENDAR_INTELLIGENCE_ENABLED:
        return

    lock_token = await _try_acquire_job_lock("cleanup_locked_at")
    if not lock_token:
        return

    try:
        supabase = get_supabase_admin_client()
        now = datetime.now(timezone.utc)
        expiry_cutoff = (now - timedelta(days=settings.CALENDAR_INTELLIGENCE_ORPHAN_EXPIRY_DAYS)).isoformat()

        orphan_statuses = [
            "notified", "awaiting_role", "awaiting_round", "awaiting_confirm",
            "orphan_no_response", "orphan_role", "orphan_round", "orphan_confirm",
        ]

        eligible = await supabase.table("calendar_event_detections") \
            .select("id") \
            .in_("detection_status", orphan_statuses) \
            .lt("created_at", expiry_cutoff) \
            .execute_async()

        ids = [row["id"] for row in (eligible.data or [])]
        if ids:
            await supabase.table("calendar_event_detections") \
                .update({
                    "detection_status": "expired",
                    "updated_at": now.isoformat(),
                }) \
                .in_("id", ids) \
                .in_("detection_status", orphan_statuses) \
                .execute_async()
            logger.info(f"Calendar Intelligence: expired {len(ids)} orphan detections")

    except Exception as e:
        logger.error(f"Calendar Intelligence cleanup_expired_detections error: {e}", exc_info=True)
    finally:
        await _release_job_lock("cleanup_locked_at", lock_token)


async def send_prep_reminders():
    """Send prep reminder emails to interviewers in a bounded pre-start window."""
    settings = get_settings()
    if not settings.CALENDAR_INTELLIGENCE_ENABLED:
        return

    lock_token = await _try_acquire_job_lock("prep_reminder_locked_at")
    if not lock_token:
        return

    try:
        supabase = get_supabase_admin_client()
        now = datetime.now(timezone.utc)
        lookahead_mins = max(1, int(settings.CALENDAR_INTELLIGENCE_PREP_LOOKAHEAD_MINUTES))
        window_end = (now + timedelta(minutes=lookahead_mins)).isoformat()

        # Find scheduled rounds in the active reminder window that haven't been reminded yet.
        result = await supabase.table("candidate_rounds") \
            .select(
                "id, scheduled_at, scheduling_timezone, interviewer_email, round_id, candidate_id, created_by_user_id"
            ) \
            .eq("status", "scheduled") \
            .eq("prep_reminder_sent", False) \
            .lte("scheduled_at", window_end) \
            .gte("scheduled_at", now.isoformat()) \
            .execute_async()

        rows = result.data or []
        if not rows:
            return

        # Batch-fetch round info and candidate info
        round_ids = list({r["round_id"] for r in rows})
        candidate_ids = list({r["candidate_id"] for r in rows})
        creator_ids = list({
            str(r.get("created_by_user_id"))
            for r in rows
            if r.get("created_by_user_id")
        })

        rounds_result = await supabase.table("rounds") \
            .select("id, name, guidelines, default_interviewer_emails") \
            .in_("id", round_ids) \
            .execute_async()
        rounds_lookup = {r["id"]: r for r in (rounds_result.data or [])}

        candidates_result = await supabase.table("candidates") \
            .select("id, name, email") \
            .in_("id", candidate_ids) \
            .execute_async()
        candidates_lookup = {c["id"]: c for c in (candidates_result.data or [])}

        creator_tz_by_id: dict[str, str] = {}
        if creator_ids:
            creator_profiles = await supabase.table("profiles") \
                .select("id, timezone") \
                .in_("id", creator_ids) \
                .execute_async()
            creator_tz_by_id = {
                str(p.get("id")): str(p.get("timezone") or "")
                for p in (creator_profiles.data or [])
                if p.get("id")
            }

        from app.services.email.service import get_email_service
        email_svc = get_email_service()

        for cr in rows:
            try:
                round_info = rounds_lookup.get(cr["round_id"])
                cand = candidates_lookup.get(cr["candidate_id"])
                if not round_info or not cand:
                    continue

                # Resolve interviewer emails: round defaults → candidate_rounds.interviewer_email
                interviewer_emails = list(round_info.get("default_interviewer_emails") or [])
                if not interviewer_emails and cr.get("interviewer_email"):
                    interviewer_emails = [cr["interviewer_email"]]

                if not interviewer_emails:
                    logger.debug(f"Prep reminder: no interviewer email for candidate_round={cr['id']}, skipping")
                    continue

                guidelines_html = build_guidelines_html(round_info.get("guidelines") or [])

                tz_hint = str(cr.get("scheduling_timezone") or "").strip()
                if not tz_hint:
                    tz_hint = creator_tz_by_id.get(str(cr.get("created_by_user_id") or ""), "")
                scheduled_at_display = format_event_time_for_email(cr.get("scheduled_at"), tz_hint)
                round_name = round_info.get("name", "Round")
                candidate_name = cand.get("name", "Unknown")

                sent = False
                for email in interviewer_emails:
                    try:
                        interviewer_name = email.split("@")[0].replace(".", " ").replace("_", " ").title()
                        email_result = await email_svc.send_templated_email(
                            to_email=email,
                            to_name=interviewer_name,
                            subject=f"Starting Soon — {round_name} — {candidate_name}",
                            template_name="prep_reminder.html",
                            context={
                                "interviewer_name": interviewer_name,
                                "candidate_name": candidate_name,
                                "candidate_email": cand.get("email", ""),
                                "round_name": round_name,
                                "scheduled_at": scheduled_at_display,
                                "guidelines_html": guidelines_html,
                            },
                        )
                        if email_result.success:
                            sent = True
                            logger.info(f"Prep reminder: sent to {email} for candidate_round={cr['id']}")
                        else:
                            logger.warning(f"Prep reminder: failed for {email}: {email_result.error}")
                    except Exception as e:
                        logger.error(f"Prep reminder: email error for {email}: {e}")

                if sent:
                    await supabase.table("candidate_rounds") \
                        .update({"prep_reminder_sent": True, "updated_at": now.isoformat()}) \
                        .eq("id", cr["id"]) \
                        .eq("prep_reminder_sent", False) \
                        .execute_async()

            except Exception as e:
                logger.error(f"Prep reminder: error processing candidate_round={cr.get('id')}: {e}")

    except Exception as e:
        logger.error(f"Prep reminder send_prep_reminders error: {e}", exc_info=True)
    finally:
        await _release_job_lock("prep_reminder_locked_at", lock_token)


_INTERVAL_LOOP_MIN_SLEEP_SECONDS = 5
_INTERVAL_LOOP_FAILURE_ESCALATION = 3


async def _interval_loop(name: str, job, interval_seconds: int) -> None:
    """Run `job` forever every `interval_seconds`. Replaces one APScheduler
    interval job. Single-instance safety comes from the DB CAS locks inside
    each job (calendar_intelligence_state), not from this wrapper.

    Resilience:
      - the sleep is floored at _INTERVAL_LOOP_MIN_SLEEP_SECONDS so a
        misconfigured 0s interval can never become a tight busy-loop;
      - after _INTERVAL_LOOP_FAILURE_ESCALATION consecutive job failures the
        log escalates to ERROR (a silently-dead loop is otherwise invisible);
        the counter resets on the first successful run."""
    logger.info(f"Calendar Intelligence loop '{name}' started (interval={interval_seconds}s)")
    sleep_seconds = max(_INTERVAL_LOOP_MIN_SLEEP_SECONDS, interval_seconds)
    consecutive_failures = 0
    while True:
        try:
            await job()
            consecutive_failures = 0
        except asyncio.CancelledError:
            logger.info(f"Calendar Intelligence loop '{name}' cancelled")
            raise
        except Exception as e:
            consecutive_failures += 1
            if consecutive_failures >= _INTERVAL_LOOP_FAILURE_ESCALATION:
                logger.error(
                    f"Calendar Intelligence loop '{name}' error "
                    f"({consecutive_failures} consecutive failures): {e}"
                )
            else:
                logger.warning(f"Calendar Intelligence loop '{name}' error: {e}")
        await asyncio.sleep(sleep_seconds)


async def run_calendar_intelligence_loops() -> None:
    """v2 replacement for register_scheduler(): one asyncio loop per job.
    No-op when the feature is disabled. Started by the FastAPI lifespan."""
    settings = get_settings()
    if not settings.CALENDAR_INTELLIGENCE_ENABLED:
        logger.info("Calendar Intelligence disabled, not starting loops")
        return
    await asyncio.gather(
        _interval_loop("poll", poll_and_detect, settings.CALENDAR_INTELLIGENCE_POLL_INTERVAL),
        _interval_loop("orphan_reminders", process_orphan_reminders, settings.CALENDAR_INTELLIGENCE_REMINDER_INTERVAL),
        _interval_loop("cleanup", cleanup_expired_detections, 3600),
        _interval_loop("prep_reminders", send_prep_reminders, settings.CALENDAR_INTELLIGENCE_PREP_REMINDER_INTERVAL),
    )


async def run_deferred_backfill() -> None:
    """One-shot startup backfill (ported from v1 main.py startup hook).
    CAS-grabs the backfill_lock row, runs gcal.backfill_recall_registrations(),
    clears the lock. No-op when disabled."""
    settings = get_settings()
    if not settings.CALENDAR_INTELLIGENCE_ENABLED:
        return
    await asyncio.sleep(10)
    try:
        sb = get_supabase_admin_client()
        lock = await sb.table("calendar_intelligence_state") \
            .update({"value": "running", "updated_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("key", "backfill_lock") \
            .is_("value", "null") \
            .execute_async()
        if not lock.data:
            logger.info("Calendar Intelligence: backfill already running on another instance, skipping")
            return
        try:
            from app.services.google_calendar_service import get_google_calendar_service
            result = await get_google_calendar_service().backfill_recall_registrations()
            logger.info(f"Calendar Intelligence: backfill result={result}")
        finally:
            await sb.table("calendar_intelligence_state") \
                .update({"value": None, "updated_at": datetime.now(timezone.utc).isoformat()}) \
                .eq("key", "backfill_lock") \
                .execute_async()
    except Exception as e:
        logger.warning(f"Calendar Intelligence: backfill failed (non-blocking): {e}")
