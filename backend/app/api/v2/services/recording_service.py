"""
Recording-URL + transcript read endpoints.

Endpoints owned:
  GET /candidate-rounds/{cr_id}/recording-url
  GET /candidate-rounds/{cr_id}/transcript
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.api.v2.core.exceptions import NotFoundError, UpstreamServiceError
from app.api.v2.services.journey_service import load_cr_with_round_for_org
from app.logging_config import get_logger


logger = get_logger(__name__)


# TTL for cached pre-signed recording URLs. Recall.ai's pre-signed S3
# links have a soft ~60-minute window; we cache for slightly less so we
# never serve a URL that's about to expire mid-playback. The cached value
# lives in `recall_bots.recording_url` + `recording_url_expires_at`
# (migration 86); when the row's expires_at is in the past we re-mint
# from Recall on the next read.
_RECORDING_URL_CACHE_TTL_MINUTES = 50

# Bot statuses that mean a recording is fully available for download.
# Mirrors the v1 endpoint behaviour (v1 only calls get_recording_urls when
# bot.status == 'done'). 'processing' / 'call_ended' are post-meeting but
# pre-render — recording_url isn't populated yet.
_RECORDING_READY_STATUSES = {"done"}


def _parse_iso_utc(value: Any) -> datetime | None:
    """Lenient ISO-8601 parser for recording_url_expires_at. Returns None
    when the column is null or malformed — caller treats unknown TTL as
    expired."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


async def _latest_recall_bot(supabase, cr_id: UUID, columns: str) -> dict | None:
    """Most-recent recall_bots row for a round."""
    own = await (
        supabase.table("recall_bots")
        .select(columns)
        .eq("candidate_round_id", str(cr_id))
        .order("created_at", desc=True)
        .limit(1)
        .execute_async()
    )
    rows = own.data or []
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# GET /candidate-rounds/{cr_id}/recording-url
# ---------------------------------------------------------------------------


def _recording_not_ready(bot_status: Any) -> HTTPException:
    """Build the dict-shape 409 the legacy endpoint returns when the
    recording is still rendering. Kept as an HTTPException because the
    response body is a dict, not a string — our standard ConflictError
    handler serialises only the human-message string."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": "Recording not ready yet",
            "bot_status": bot_status,
        },
    )


async def get_recording_url(supabase, org_id: str, cr_id: UUID) -> dict:
    # Org-scope the CR via the shared helper.
    await load_cr_with_round_for_org(supabase, cr_id, org_id)

    # Pull the TTL column too so we can decide cache hit vs re-mint without a
    # second trip.
    bot = await _latest_recall_bot(
        supabase,
        cr_id,
        "id, recall_bot_id, status, recording_url, recording_url_expires_at",
    )
    if not bot:
        raise NotFoundError("No recording found for this round")

    bot_status = bot.get("status")
    cached_recording_url = bot.get("recording_url")

    if bot_status not in _RECORDING_READY_STATUSES:
        raise _recording_not_ready(bot_status)

    # Cache hit: cached URL exists AND expires_at is in the future. Note
    # we DELIBERATELY do not use cached_recording_url to early-out when
    # expires_at is null — a null TTL means "we have a URL but no idea
    # when it expires" (e.g. data pre-migration-86) and the safe move is
    # to re-mint.
    now = datetime.now(timezone.utc)
    cached_expires_at = _parse_iso_utc(bot.get("recording_url_expires_at"))
    if cached_recording_url and cached_expires_at and cached_expires_at > now:
        logger.info(
            "v2 recording-url: cache hit",
            extra={
                "event": "recording_url.cache_hit",
                "cr_id": str(cr_id),
                "bot_id": bot.get("recall_bot_id"),
                "expires_in_s": int((cached_expires_at - now).total_seconds()),
            },
        )
        return {"url": cached_recording_url, "expires_at": cached_expires_at.isoformat()}

    # Cache miss / stale: re-mint from Recall.
    logger.info(
        "v2 recording-url: cache miss (refreshing)",
        extra={
            "event": "recording_url.cache_miss",
            "cr_id": str(cr_id),
            "bot_id": bot.get("recall_bot_id"),
            "had_cached_url": bool(cached_recording_url),
            "had_expires_at": cached_expires_at is not None,
        },
    )

    from app.services.recall_service import (
        RecallServiceError,
        get_recall_service,
    )

    recall_service = get_recall_service()
    try:
        try:
            recording_data = await recall_service.get_recording_urls(bot["recall_bot_id"])
        except RecallServiceError as e:
            logger.error(
                "v2 recording-url: Recall API error cr_id=%s bot_id=%s status=%s details=%s",
                str(cr_id), bot.get("recall_bot_id"),
                getattr(e, "status_code", None), getattr(e, "details", None),
            )
            raise UpstreamServiceError(
                "Failed to retrieve recording URL from Recall.ai",
                status_code=502,
            )
        except Exception as e:
            logger.error(
                "v2 recording-url: unexpected error cr_id=%s bot_id=%s error=%s",
                str(cr_id), bot.get("recall_bot_id"), str(e),
            )
            raise UpstreamServiceError(
                "Failed to retrieve recording URL from Recall.ai",
                status_code=502,
            )
    finally:
        await recall_service.close()

    fresh_url = (recording_data or {}).get("video_url") if recording_data else None
    if not fresh_url:
        # Recall returned no usable URL even though our DB says it should be
        # ready. Treat as "still rendering" — same 409 the recruiter sees
        # before render completes.
        logger.warning(
            "v2 recording-url: Recall returned no video_url cr_id=%s bot_id=%s",
            str(cr_id), bot.get("recall_bot_id"),
        )
        raise _recording_not_ready(bot_status)

    expires_at_dt = now + timedelta(minutes=_RECORDING_URL_CACHE_TTL_MINUTES)
    expires_at_iso = expires_at_dt.isoformat()

    # Write back to the cache. Failures here are NOT fatal — the recruiter
    # still gets the URL; the next call will re-mint instead of hitting the
    # cache. This is the right trade: never let a write hiccup block a read.
    try:
        await (
            supabase.table("recall_bots")
            .update({
                "recording_url": fresh_url,
                "recording_url_expires_at": expires_at_iso,
            })
            .eq("id", bot["id"])
            .execute_async()
        )
    except Exception as cache_err:
        logger.warning(
            "v2 recording-url: cache write failed cr_id=%s bot_id=%s err=%s",
            str(cr_id), bot.get("recall_bot_id"), str(cache_err),
        )

    return {"url": fresh_url, "expires_at": expires_at_iso}


# ---------------------------------------------------------------------------
# GET /candidate-rounds/{cr_id}/transcript
# ---------------------------------------------------------------------------


def _flatten_recall_segment(raw: dict) -> dict | None:
    """Normalize one Recall.ai transcript segment into the v2 wire shape
    `{speaker, text, ts_start, ts_end}`.

    Recall stores each utterance as `{words: [{text, start_timestamp:
    {relative}, end_timestamp: {relative}}, ...], participant: {name, ...}}`.
    The v2 frontend (and the packet drawer's transcript pane) expects a flat
    object per segment — we collapse words into a single text string and
    take ts_start from the first word, ts_end from the last word.
    """
    words = raw.get("words") or []
    if not words:
        return None
    text_parts: list[str] = []
    ts_start: float | None = None
    ts_end: float | None = None
    for w in words:
        t = w.get("text")
        if t:
            text_parts.append(t)
        start = (w.get("start_timestamp") or {}).get("relative")
        end = (w.get("end_timestamp") or {}).get("relative")
        if start is not None:
            ts_start = start if ts_start is None else min(ts_start, start)
        if end is not None:
            ts_end = end if ts_end is None else max(ts_end, end)
    text = " ".join(text_parts).strip()
    if not text:
        return None
    participant = raw.get("participant") or {}
    speaker = participant.get("name") or "Unknown"
    return {
        "speaker": speaker,
        "text": text,
        "ts_start": float(ts_start or 0.0),
        "ts_end": float(ts_end or 0.0),
    }


async def _lazy_ingest_transcript_from_recall(
    supabase, cr_id: UUID, transcript_url: str
) -> list[dict] | None:
    """Fetch the transcript JSON from Recall's S3 link and upsert into the
    transcripts table. Returns the freshly-fetched segments array, or None
    on failure. Idempotent — uses upsert on candidate_round_id.

    Why this lives here: the Recall webhook flow that populates
    `transcripts.segments` doesn't always fire (e.g., webhooks lost during
    backend deploys). When
    the bot itself has `transcript_ready=true` and a pre-signed `transcript_url`,
    that data is the source of truth — we just haven't cached it yet.
    """
    # Reuse the module-level pooled httpx client. Creating a fresh client
    # per call costs connection pool warm-up and ignores the keep-alive
    # limits configured on the singleton.
    from app.services.supabase import get_async_http_client

    try:
        client = get_async_http_client()
        resp = await client.get(transcript_url, timeout=30.0)
        if resp.status_code != 200:
            logger.warning(
                "v2 transcript: Recall S3 fetch non-200 cr_id=%s status=%s",
                str(cr_id), resp.status_code,
            )
            return None
        recall_data = resp.json()
    except Exception as e:
        logger.warning(
            "v2 transcript: Recall S3 fetch failed cr_id=%s err=%s",
            str(cr_id), str(e),
        )
        return None

    # Recall returns either a list of segments directly, or wraps under
    # a "transcript"/"segments" key depending on the API version. Support
    # both shapes defensively.
    if isinstance(recall_data, dict):
        segments = (
            recall_data.get("segments")
            or recall_data.get("transcript")
            or []
        )
    elif isinstance(recall_data, list):
        segments = recall_data
    else:
        segments = []

    if not segments:
        return None

    # Best-effort upsert; ignore write errors so a read-only DB role doesn't
    # break the GET path. The fetched data is still returned to the caller.
    try:
        await (
            supabase.table("transcripts")
            .upsert(
                {
                    "candidate_round_id": str(cr_id),
                    "segments": segments,
                    "raw_transcript_url": transcript_url,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="candidate_round_id",
            )
            .execute_async()
        )
    except Exception as e:
        logger.warning(
            "v2 transcript: lazy ingest upsert failed cr_id=%s err=%s",
            str(cr_id), str(e),
        )

    return segments


async def get_transcript(supabase, org_id: str, cr_id: UUID) -> dict:
    # First, verify the candidate_round belongs to this org. Embedded select
    # traverses candidate_rounds → candidates → requisitions.
    cr_result = await (
        supabase.table("candidate_rounds")
        .select("id, candidates(requisition_id, requisitions(organization_id))")
        .eq("id", str(cr_id))
        .single()
        .execute_async()
    )
    if not cr_result.data:
        raise NotFoundError("Transcript not found")

    cand = cr_result.data.get("candidates") or {}
    req = cand.get("requisitions") or {}
    if req.get("organization_id") != org_id:
        # Don't leak whether the CR exists in a different org.
        raise NotFoundError("Transcript not found")

    transcript_result = await (
        supabase.table("transcripts")
        .select("segments, duration_seconds, word_count")
        .eq("candidate_round_id", str(cr_id))
        .single()
        .execute_async()
    )
    if not transcript_result.data:
        raise NotFoundError("Transcript not found")

    t = transcript_result.data
    raw_segments = t.get("segments") or []
    # Recall.ai stores each segment as `{words: [...], participant: {...}}` —
    # flatten before returning so the v2 FE doesn't have to parse Recall's
    # internal shape.
    flat_segments: list[dict] = []
    for raw in raw_segments:
        if not isinstance(raw, dict):
            continue
        # Pass-through path for already-flat segments (defensive — manual
        # backfills or future ingestion shapes that match the wire contract).
        if "text" in raw and ("ts_start" in raw or "start_seconds" in raw):
            flat_segments.append({
                "speaker": raw.get("speaker") or "Unknown",
                "text": raw["text"],
                "ts_start": float(raw.get("ts_start") or raw.get("start_seconds") or 0.0),
                "ts_end": float(raw.get("ts_end") or raw.get("end_seconds") or 0.0),
            })
            continue
        flat = _flatten_recall_segment(raw)
        if flat is not None:
            flat_segments.append(flat)

    duration = t.get("duration_seconds")
    # Fall back to the last segment's end timestamp when transcripts row is
    # missing duration_seconds (common — the Recall ingestion doesn't always
    # write this column).
    if duration is None and flat_segments:
        duration = int(max(s["ts_end"] for s in flat_segments))

    # Surface feedback_start_seconds (interview ↔ feedback split) by reading
    # recall_bots.feedback_started_at relative to joined_at. The drawer uses
    # this to render the segment toggle. Also doubles as the source for the
    # lazy transcript ingest when our DB row is empty but Recall has it.
    bot = await _latest_recall_bot(
        supabase,
        cr_id,
        "joined_at, feedback_started_at, recording_duration_seconds, "
        "transcript_url, transcript_ready",
    )

    # Lazy ingest: if our transcripts row is empty AND the bot has a ready
    # transcript URL, fetch it from Recall, upsert into the transcripts
    # table, and use those segments. The Recall webhook flow misses some
    # rounds (deploy-time webhook loss), and from
    # the recruiter's POV the gap looks like "we never recorded a
    # transcript" which is wrong — the data exists, we just hadn't cached
    # it. Run once per round; subsequent calls hit the cached transcripts
    # row instead.
    if not flat_segments and bot is not None:
        bot_for_ingest = bot
        if bot_for_ingest.get("transcript_ready") and bot_for_ingest.get("transcript_url"):
            fetched = await _lazy_ingest_transcript_from_recall(
                supabase, cr_id, bot_for_ingest["transcript_url"]
            )
            if fetched:
                for raw in fetched:
                    if not isinstance(raw, dict):
                        continue
                    if "text" in raw and ("ts_start" in raw or "start_seconds" in raw):
                        flat_segments.append({
                            "speaker": raw.get("speaker") or "Unknown",
                            "text": raw["text"],
                            "ts_start": float(raw.get("ts_start") or raw.get("start_seconds") or 0.0),
                            "ts_end": float(raw.get("ts_end") or raw.get("end_seconds") or 0.0),
                        })
                        continue
                    flat = _flatten_recall_segment(raw)
                    if flat is not None:
                        flat_segments.append(flat)
                if duration is None and flat_segments:
                    duration = int(max(s["ts_end"] for s in flat_segments))
    feedback_start_seconds: float | None = None
    if bot is not None:
        joined = bot.get("joined_at")
        fb_started = bot.get("feedback_started_at")
        if joined and fb_started:
            try:
                joined_dt = datetime.fromisoformat(joined.replace("Z", "+00:00"))
                fb_dt = datetime.fromisoformat(fb_started.replace("Z", "+00:00"))
                offset = (fb_dt - joined_dt).total_seconds()
                if offset > 0:
                    feedback_start_seconds = float(offset)
            except (ValueError, TypeError):
                feedback_start_seconds = None
        # Recall's recording_duration_seconds is more authoritative than
        # transcript.duration_seconds when both are present (the transcript
        # may end before the bot stopped recording).
        bot_duration = bot.get("recording_duration_seconds")
        if bot_duration is not None and (duration is None or bot_duration > duration):
            duration = bot_duration

    return {
        "segments": flat_segments,
        "duration_seconds": duration,
        "word_count": t.get("word_count"),
        "feedback_start_seconds": feedback_start_seconds,
    }
