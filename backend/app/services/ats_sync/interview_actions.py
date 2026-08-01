"""Phase C: act on interviews promoted by ats_promote_interviews.

For each promoted interview row (candidate_round now exists):
  (a) future + meeting_url  -> schedule a Recall bot (auto-join, no flag).
  (b) notetaker_transcript_id -> pull + store the transcript (best-effort).
  (c) transcript present + feedback_questions present -> trigger feedback
      (skip_prereq_check=True, so NOT guarded by the feedback claim CAS).

Every external side effect is best-effort: a failure on one interview logs
and the loop continues. The "act on each interview exactly once" guarantee is
NOT from idempotent side effects — Recall re-schedule is cancel+recreate and
feedback runs with skip_prereq_check=True, which BYPASSES the
claim_feedback_processing CAS. It comes from upstream: ats_promote_interviews
only returns interviews with candidate_round_id IS NULL and sets
candidate_round_id on each promoted row in the same transaction (migration
131), so a re-promote never re-returns an already-acted interview.

De-dup precedence (spec §11): if a Recall bot was scheduled for the CR, the
notetaker transcript is NOT written to candidate_rounds.scorecard_transcript
— the recall webhook will write diarized transcripts.segments and the Lambda
prefers scorecard_transcript > segments. The notetaker text is only written
to scorecard_transcript when no Recall bot was scheduled (no meeting URL).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.api.v2.services.recall_orchestrator import create_recall_bot_for_cr
from app.integrations.ats.core.registry import get_ats_provider
from app.logging_config import get_logger
from app.services.feedback_job_service import (
    get_feedback_job_service,
)
from app.utils import parse_iso_datetime

logger = get_logger(__name__)


# Neutral speaker labels — NEVER "OpenRecruiting"/"OpenRecruiting"/"OpenRecruiting Interview
# Assistant" (recall_webhook/constants.py BOT_SPEAKER_NAMES landmine:
# bot-labelled segments are dropped by the feedback Lambda).
_INTERVIEWER_LABEL = "Interviewer"
_CANDIDATE_LABEL = "Candidate"


def _format_segments(segments: list[dict] | None) -> tuple[list[dict], str]:
    """Normalize notetaker segments to neutral speaker labels and a flat
    text. Returns (neutral_segments, flat_text). Maps any 'candidate'-ish
    role to Candidate and everything else to Interviewer (NEVER 'OpenRecruiting*')."""
    neutral: list[dict] = []
    lines: list[str] = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        raw = str(seg.get("speaker") or "").strip().lower()
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        label = _CANDIDATE_LABEL if "candidate" in raw else _INTERVIEWER_LABEL
        neutral.append({"speaker": label, "text": text})
        lines.append(f"{label}: {text}")
    return neutral, "\n".join(lines)


async def _store_notetaker_transcript(
    supabase, cr_id: str, transcript, recall_scheduled: bool
) -> bool:
    """Store the notetaker transcript for a CR. Returns True if usable text
    was stored. De-dup precedence: when a Recall bot is scheduled we do NOT
    write scorecard_transcript (Recall's diarized segments win); we only flag
    the ats_interviews row. When no Recall bot, write the flattened text to
    candidate_rounds.scorecard_transcript so the Lambda picks it up."""
    segments = getattr(transcript, "segments", None)
    # Real AtsTranscript exposes `.text`; the test stand-in uses `.full_text`.
    full_text = getattr(transcript, "full_text", None) or getattr(
        transcript, "text", None
    )
    _neutral, flat = _format_segments(segments)
    text = flat or (str(full_text).strip() if full_text else "")
    if not text:
        return False

    if not recall_scheduled:
        await (
            supabase.table("candidate_rounds")
            .update({"scorecard_transcript": text})
            .eq("id", cr_id)
            .execute_async()
        )
    # else: precedence — leave scorecard_transcript untouched; Recall webhook
    # writes transcripts.segments and the Lambda prefers it.
    return True


async def _pull_transcript(
    supabase, row: dict, bundle, recall_scheduled: bool
) -> bool:
    """Best-effort notetaker pull + store. Returns True if a transcript was
    stored to scorecard_transcript (i.e. the Lambda now has feedback input
    from notetaker). Never raises."""
    nt_id = row.get("notetaker_transcript_id")
    event_id = row.get("ats_interview_event_id")
    interviews = getattr(bundle, "interviews", None) if bundle else None
    if not (nt_id and interviews):
        return False
    try:
        transcript = await interviews.fetch_transcript(nt_id)
    except Exception as exc:
        logger.warning(
            "ats_interview_transcript_fetch_failed",
            extra={
                "event": "ats_interview_transcript_fetch_failed",
                "notetaker_transcript_id": nt_id,
                "error": str(exc),
            },
        )
        return False
    if transcript is None:
        return False

    cr_id = row["candidate_round_id"]
    try:
        stored = await _store_notetaker_transcript(
            supabase, cr_id, transcript, recall_scheduled
        )
    except Exception as exc:
        logger.warning(
            "ats_interview_transcript_store_failed",
            extra={
                "event": "ats_interview_transcript_store_failed",
                "candidate_round_id": cr_id,
                "error": str(exc),
            },
        )
        return False

    if not stored:
        return False

    if event_id:
        # transcript_source accumulates: 'notetaker' or 'both' if recall too.
        source = "both" if recall_scheduled else "notetaker"
        try:
            await (
                supabase.table("ats_interviews")
                .update(
                    {"transcript_status": "pulled", "transcript_source": source}
                )
                .eq("ats_interview_event_id", event_id)
                .execute_async()
            )
        except Exception as exc:
            logger.warning(
                "ats_interview_transcript_flag_failed",
                extra={
                    "event": "ats_interview_transcript_flag_failed",
                    "ats_interview_event_id": event_id,
                    "error": str(exc),
                },
            )
    # Only signals "notetaker text is now in scorecard_transcript" (feedback-
    # usable) when we actually wrote it — i.e. no recall scheduled.
    return stored and not recall_scheduled


async def trigger_feedback_processing(
    cr_id: str, skip_prereq_check: bool = False
) -> dict:
    """Thin module-level seam so tests monkeypatch one symbol. Delegates to
    the existing FeedbackJobService (boto3 Lambda + claim CAS)."""
    return await get_feedback_job_service().trigger_feedback_processing(
        cr_id, skip_prereq_check=skip_prereq_check
    )


def _is_future(scheduled_start: Optional[str]) -> bool:
    if not scheduled_start:
        return False
    try:
        when = parse_iso_datetime(scheduled_start)
    except (ValueError, TypeError):
        return False
    return when.astimezone(timezone.utc) > datetime.now(timezone.utc)


async def _schedule_recall(supabase, row: dict) -> bool:
    """Future + meeting_url -> Recall bot. Returns True if a bot was
    scheduled (or already scheduled) for this CR, so the caller can apply
    the de-dup precedence. 409 lock -> log + skip, returns True (a bot is
    in flight from a concurrent pass). Other failure -> log, returns False."""
    cr_id = row.get("candidate_round_id")
    meeting_url = row.get("meeting_url")
    scheduled_start = row.get("scheduled_start")
    event_id = row.get("ats_interview_event_id")

    if not (cr_id and meeting_url and _is_future(scheduled_start)):
        if cr_id and not meeting_url:
            logger.info(
                "ats_interview_recall_skipped_no_url",
                extra={
                    "event": "ats_interview_recall_skipped_no_url",
                    "candidate_round_id": cr_id,
                    "ats_interview_event_id": event_id,
                },
            )
        return False

    try:
        scheduled_at = parse_iso_datetime(scheduled_start).astimezone(timezone.utc)
    except (ValueError, TypeError):
        logger.warning(
            "ats_interview_recall_bad_time",
            extra={
                "event": "ats_interview_recall_bad_time",
                "candidate_round_id": cr_id,
                "scheduled_start": scheduled_start,
            },
        )
        return False

    candidate_name = row.get("candidate_name") or "Candidate"
    try:
        bot = await create_recall_bot_for_cr(
            cr_id=cr_id,
            candidate_name=candidate_name,
            meeting_url=meeting_url,
            scheduled_at=scheduled_at,
        )
    except Exception as exc:  # HTTPException(409) lock or any transient error
        status = getattr(exc, "status_code", None)
        if status == 409:
            logger.info(
                "ats_interview_recall_lock_skip",
                extra={
                    "event": "ats_interview_recall_lock_skip",
                    "candidate_round_id": cr_id,
                    "ats_interview_event_id": event_id,
                },
            )
            return True  # a concurrent pass is scheduling — treat as scheduled
        logger.warning(
            "ats_interview_recall_failed",
            extra={
                "event": "ats_interview_recall_failed",
                "candidate_round_id": cr_id,
                "error": str(exc),
            },
        )
        return False

    # create_recall_bot_for_cr RETURNS None on a real Recall failure (it only
    # re-raises HTTPException for the 409 lock; every other failure is logged +
    # swallowed -> None). "No exception" is NOT success — a None bot means no
    # notetaker was scheduled, so return False to let the notetaker fallback fire
    # (otherwise the de-dup precedence would suppress it and silently lose the
    # transcript + feedback).
    if not bot:
        logger.warning(
            "ats_interview_recall_failed",
            extra={
                "event": "ats_interview_recall_failed",
                "candidate_round_id": cr_id,
                "ats_interview_event_id": event_id,
            },
        )
        return False

    if event_id:
        try:
            await (
                supabase.table("ats_interviews")
                .update({"recall_bot_scheduled": True})
                .eq("ats_interview_event_id", event_id)
                .execute_async()
            )
        except Exception as exc:
            logger.warning(
                "ats_interview_flag_write_failed",
                extra={
                    "event": "ats_interview_flag_write_failed",
                    "ats_interview_event_id": event_id,
                    "error": str(exc),
                },
            )
    return True


async def _has_recall_segments(supabase, cr_id: str) -> bool:
    """True if a transcripts row with non-empty segments exists for the CR
    (the recall webhook wrote it)."""
    res = await (
        supabase.table("transcripts")
        .select("id, segments")
        .eq("candidate_round_id", cr_id)
        .execute_async()
    )
    rows = res.data or []
    if not rows:
        return False
    segs = rows[0].get("segments")
    return bool(segs)


async def _round_has_feedback_questions(supabase, cr_id: str) -> bool:
    """True if the CR's round has at least one non-deleted feedback question.
    The Lambda refuses to score without them (skip_prereq_check does NOT
    bypass this)."""
    cr = await (
        supabase.table("candidate_rounds")
        .select("round_id")
        .eq("id", cr_id)
        .execute_async()
    )
    if not cr.data:
        return False
    round_id = cr.data[0].get("round_id")
    if not round_id:
        return False
    q = await (
        supabase.table("feedback_questions")
        .select("id")
        .eq("round_id", round_id)
        .is_null("deleted_at")
        .limit(1)
        .execute_async()
    )
    return bool(q.data)


async def _maybe_trigger_feedback(
    supabase, cr_id: str, notetaker_usable: bool
) -> None:
    """Trigger feedback iff a transcript exists for the CR (notetaker just
    stored to scorecard_transcript, OR Recall segments already present) AND
    the round has feedback questions. Deferred otherwise.

    NOTE: skip_prereq_check=True deliberately BYPASSES the
    claim_feedback_processing CAS (fresh ATS transcript must override an
    in-flight stale run), so this trigger is NOT self-idempotent. The guard
    against re-triggering on a re-promote is upstream: ats_promote_interviews
    only returns interviews with candidate_round_id IS NULL (migration 131),
    so each interview reaches this function exactly once."""
    has_transcript = notetaker_usable or await _has_recall_segments(supabase, cr_id)
    if not has_transcript:
        return
    if not await _round_has_feedback_questions(supabase, cr_id):
        logger.info(
            "ats_interview_feedback_deferred_no_questions",
            extra={
                "event": "ats_interview_feedback_deferred_no_questions",
                "candidate_round_id": cr_id,
            },
        )
        return
    try:
        await trigger_feedback_processing(cr_id, skip_prereq_check=True)
    except Exception as exc:
        logger.warning(
            "ats_interview_feedback_trigger_failed",
            extra={
                "event": "ats_interview_feedback_trigger_failed",
                "candidate_round_id": cr_id,
                "error": str(exc),
            },
        )


async def act_on_promoted_interviews(
    supabase,
    promoted: list[dict[str, Any]],
    *,
    bundle=None,
) -> None:
    """Entry point. Acts on each row in `promoted` once per call. Re-running
    across ticks does NOT re-act on already-promoted interviews because
    ats_promote_interviews only returns candidate_round_id IS NULL rows
    (migration 131) — this layer's side effects are NOT self-idempotent (Recall
    is cancel+recreate, feedback bypasses the CAS via skip_prereq_check=True).

    `bundle` is the AtsProviderBundle (for bundle.interviews.fetch_transcript);
    resolved from the first row's organization_id when not supplied so callers
    that don't already hold one (reconcile) need not construct it."""
    if not promoted:
        return

    if bundle is None:
        org_id = next(
            (r.get("organization_id") for r in promoted if r.get("organization_id")),
            None,
        )
        if org_id:
            try:
                bundle = await get_ats_provider(supabase, org_id)
            except Exception as exc:
                logger.warning(
                    "ats_interview_bundle_resolve_failed",
                    extra={
                        "event": "ats_interview_bundle_resolve_failed",
                        "organization_id": str(org_id),
                        "error": str(exc),
                    },
                )
                bundle = None

    for row in promoted:
        cr_id = row.get("candidate_round_id")
        if not cr_id:
            # Deferred: no candidate_round yet — nothing to act on. The next
            # promotion/reconcile pass will carry a cr_id once it exists.
            continue
        try:
            recall_scheduled = await _schedule_recall(supabase, row)
            notetaker_usable = await _pull_transcript(
                supabase, row, bundle, recall_scheduled
            )
            await _maybe_trigger_feedback(supabase, cr_id, notetaker_usable)
        except Exception as exc:  # never let one row abort the batch
            logger.warning(
                "ats_interview_action_error",
                extra={
                    "event": "ats_interview_action_error",
                    "candidate_round_id": cr_id,
                    "error": str(exc),
                },
            )
