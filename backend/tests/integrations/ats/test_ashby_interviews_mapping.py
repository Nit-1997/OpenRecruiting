"""Pure Ashby interviewSchedule → AtsInterview mapping (real probed shapes)."""

from app.integrations.ats.passthrough.ashby.interviews_mapping import (
    interviewer_from_wire,
    interviews_from_schedule,
    meeting_url_from_event,
    transcript_from_wire,
)


def _schedule() -> dict:
    """Mirrors the live interviewSchedule.list item (verified 2026-06-14)."""
    return {
        "id": "sched-1",
        "status": "Scheduled",
        "applicationId": "app-1",
        "interviewStageId": "stage-1",
        "scheduledBy": "user-9",
        "createdAt": "2026-06-14T03:06:00.000Z",
        "updatedAt": "2026-06-14T03:06:00.000Z",
        "interviewEvents": [
            {
                "id": "evt-1",
                "interviewId": "interview-1",
                "interviewScheduleId": "sched-1",
                "interviewerUserIds": ["user-1", "user-2"],
                "interviewers": [
                    {"id": "user-1", "firstName": "Ada", "lastName": "Lovelace",
                     "email": "ada@example.com", "globalRole": "Org Admin",
                     "isEnabled": True, "isFeedbackRequired": True},
                    {"id": "user-2", "firstName": "Alan", "lastName": "Turing",
                     "email": "alan@example.com", "globalRole": "Interviewer",
                     "isEnabled": True, "isFeedbackRequired": False},
                ],
                "startTime": "2026-06-20T17:00:00.000Z",
                "endTime": "2026-06-20T18:00:00.000Z",
                "feedbackLink": "https://app.ashbyhq.com/feedback/evt-1",
                "hasSubmittedFeedback": False,
                "extraData": {},
            }
        ],
    }


def test_maps_schedule_to_one_interview_per_event():
    stage_titles = {"stage-1": "Technical Screen"}
    interview_titles = {"interview-1": "System Design"}
    out = interviews_from_schedule(_schedule(), stage_titles, interview_titles)
    assert len(out) == 1
    iv = out[0]
    assert iv.event_id == "evt-1"
    assert iv.application_id == "app-1"
    assert iv.schedule_id == "sched-1"
    assert iv.interview_id == "interview-1"
    assert iv.stage_id == "stage-1"
    assert iv.stage_name == "Technical Screen"
    assert iv.interview_title == "System Design"
    assert iv.scheduled_start == "2026-06-20T17:00:00.000Z"
    assert iv.scheduled_end == "2026-06-20T18:00:00.000Z"
    assert iv.status == "Scheduled"          # falls back to schedule status
    assert iv.feedback_link == "https://app.ashbyhq.com/feedback/evt-1"
    assert iv.has_submitted_feedback is False
    assert iv.meeting_url is None            # no location in sandbox


def test_maps_interviewers():
    out = interviews_from_schedule(_schedule(), {}, {})
    who = out[0].interviewers
    assert [w.email for w in who] == ["ada@example.com", "alan@example.com"]
    assert who[0].name == "Ada Lovelace"
    assert who[0].ats_user_id == "user-1"


def test_event_level_status_overrides_schedule_status():
    sched = _schedule()
    sched["interviewEvents"][0]["status"] = "Completed"
    out = interviews_from_schedule(sched, {}, {})
    assert out[0].status == "Completed"


def test_missing_stage_or_interview_title_is_none():
    out = interviews_from_schedule(_schedule(), {}, {})  # empty lookup maps
    assert out[0].stage_name is None
    assert out[0].interview_title is None


def test_schedule_with_no_events_yields_empty():
    sched = _schedule()
    sched["interviewEvents"] = []
    assert interviews_from_schedule(sched, {}, {}) == []


def test_non_dict_event_skipped():
    sched = _schedule()
    sched["interviewEvents"] = [None, sched["interviewEvents"][0]]
    out = interviews_from_schedule(sched, {}, {})
    assert len(out) == 1
    assert out[0].event_id == "evt-1"


def test_interviewer_from_wire_partial():
    who = interviewer_from_wire({"id": "u-9", "firstName": "Grace", "email": "g@x.co"})
    assert who.name == "Grace"
    assert who.email == "g@x.co"
    assert who.ats_user_id == "u-9"


def test_interviewer_from_wire_non_dict_returns_none():
    assert interviewer_from_wire("nope") is None
    assert interviewer_from_wire(None) is None


def test_meeting_url_from_extradata_location():
    ev = {"extraData": {"location": "https://meet.google.com/abc"}}
    assert meeting_url_from_event(ev) == "https://meet.google.com/abc"


def test_meeting_url_from_top_level_location():
    ev = {"location": "https://zoom.us/j/55"}
    assert meeting_url_from_event(ev) == "https://zoom.us/j/55"


def test_meeting_url_absent_returns_none():
    assert meeting_url_from_event({"extraData": {}}) is None
    assert meeting_url_from_event({}) is None


def test_transcript_from_wire_segments_and_text():
    results = {
        "transcript": [
            {"speaker": "Interviewer", "text": "Tell me about yourself"},
            {"speaker": "Candidate", "text": "I build systems"},
        ]
    }
    t = transcript_from_wire(results, source="notetaker")
    assert t is not None
    assert t.source == "notetaker"
    assert len(t.segments) == 2
    assert t.segments[0] == {"speaker": "Interviewer", "text": "Tell me about yourself"}
    assert "I build systems" in (t.text or "")


def test_transcript_from_wire_empty_returns_none():
    assert transcript_from_wire({}, source="notetaker") is None
    assert transcript_from_wire(None, source="notetaker") is None
