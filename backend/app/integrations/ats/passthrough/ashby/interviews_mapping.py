"""Pure Ashby-native wire→canonical interview mapping (interviewSchedule.list).

One interviewEvent → one AtsInterview. Stage/interview titles are looked up from
per-call caches the adapter builds (interviewStage.list / interview.list). Meeting
URL is opportunistic: extraData.location or a top-level location, else None
(sandbox has neither — spec §3 CONSTRAINT 1)."""

from app.integrations.ats.core.models import (
    AtsInterview,
    AtsInterviewer,
    AtsInterviewStage,
    AtsTranscript,
)


def stage_from_wire(raw, *, fallback_plan_id: str | None = None) -> AtsInterviewStage | None:
    """interviewStage.list row → AtsInterviewStage. Live shape:
    {id, title, type, orderInInterviewPlan, interviewPlanId, interviewStageGroupId}.
    Returns None for non-dict / id-less rows."""
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    return AtsInterviewStage(
        stage_id=str(raw["id"]),
        title=raw.get("title"),
        type=raw.get("type"),
        order=int(raw.get("orderInInterviewPlan") or 0),
        interview_plan_id=raw.get("interviewPlanId") or fallback_plan_id,
    )


def interviewer_from_wire(raw) -> AtsInterviewer | None:
    if not isinstance(raw, dict):
        return None
    name = " ".join(
        p for p in (raw.get("firstName"), raw.get("lastName")) if p
    ).strip() or None
    return AtsInterviewer(
        email=raw.get("email"),
        name=name,
        ats_user_id=raw.get("id"),
    )


def _as_url(value) -> str | None:
    """Return value only if it's an actual http(s) URL — so a physical-location
    string ('Conference Room A') is never mistaken for a meeting link."""
    if isinstance(value, str) and value.strip().lower().startswith(("http://", "https://")):
        return value.strip()
    return None


def meeting_url_from_event(event: dict) -> str | None:
    """Ashby exposes the video link as `meetingLink` (camelCase), present only when
    a Zoom/Meet/Teams conferencing location is attached to the interview (Ashby docs:
    interviewEvent.list returns location + meetingLink). `location` may be a plain
    string or an object; extraData is a last-resort fallback. We only accept genuine
    URLs. (Earlier code missed Ashby's real `meetingLink` field — it only read
    location/meetingUrl.)"""
    # 1. Top-level meetingLink (Ashby's real field) / meetingUrl.
    for key in ("meetingLink", "meetingUrl"):
        url = _as_url(event.get(key))
        if url:
            return url
    # 2. location — string URL, or object carrying the link.
    loc = event.get("location")
    if isinstance(loc, dict):
        for key in ("meetingLink", "meetingUrl", "url", "joinUrl"):
            url = _as_url(loc.get(key))
            if url:
                return url
    else:
        url = _as_url(loc)
        if url:
            return url
    # 3. extraData fallback.
    extra = event.get("extraData")
    if isinstance(extra, dict):
        for key in ("meetingLink", "meetingUrl", "meeting_url", "location"):
            url = _as_url(extra.get(key))
            if url:
                return url
    return None


def _event_to_interview(
    schedule: dict, event: dict,
    stage_titles: dict[str, str], interview_titles: dict[str, str],
) -> AtsInterview:
    interviewers = [
        who
        for who in (interviewer_from_wire(i) for i in (event.get("interviewers") or []))
        if who is not None
    ]
    stage_id = schedule.get("interviewStageId")
    interview_id = event.get("interviewId")
    return AtsInterview(
        application_id=schedule.get("applicationId"),
        schedule_id=schedule.get("id"),
        event_id=event["id"],
        interview_id=interview_id,
        stage_id=stage_id,
        stage_name=stage_titles.get(stage_id) if stage_id else None,
        interview_title=interview_titles.get(interview_id) if interview_id else None,
        scheduled_start=event.get("startTime"),
        scheduled_end=event.get("endTime"),
        status=event.get("status") or schedule.get("status"),
        interviewers=interviewers,
        meeting_url=meeting_url_from_event(event),
        feedback_link=event.get("feedbackLink"),
        has_submitted_feedback=bool(event.get("hasSubmittedFeedback")),
        notetaker_transcript_id=event.get("notetakerTranscriptId"),
    )


def interviews_from_schedule(
    schedule: dict,
    stage_titles: dict[str, str],
    interview_titles: dict[str, str],
) -> list[AtsInterview]:
    if not isinstance(schedule, dict):
        return []
    out: list[AtsInterview] = []
    for event in (schedule.get("interviewEvents") or []):
        if not isinstance(event, dict) or not event.get("id"):
            continue
        out.append(_event_to_interview(schedule, event, stage_titles, interview_titles))
    return out


def transcript_from_wire(results, *, source: str) -> AtsTranscript | None:
    """notetakerTranscript.info results → AtsTranscript. Shape unverified (sandbox
    empty); read defensively. Returns None when there's no usable content."""
    if not isinstance(results, dict):
        return None
    raw_segments = results.get("transcript") or results.get("segments") or []
    segments: list[dict] = []
    if isinstance(raw_segments, list):
        for seg in raw_segments:
            if isinstance(seg, dict) and seg.get("text"):
                segments.append(
                    {"speaker": seg.get("speaker"), "text": seg.get("text")}
                )
    text = results.get("text")
    if not text and segments:
        text = "\n".join(s["text"] for s in segments)
    if not text and not segments:
        return None
    return AtsTranscript(text=text, segments=segments, source=source, raw=results)
