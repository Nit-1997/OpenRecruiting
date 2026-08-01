"""Canonical interview models: defaults, optional fields, nested interviewers."""

from app.integrations.ats.core.models import (
    AtsInterview,
    AtsInterviewer,
    AtsTranscript,
)


def test_interview_minimal_only_event_id():
    iv = AtsInterview(event_id="evt-1")
    assert iv.event_id == "evt-1"
    assert iv.interviewers == []
    assert iv.meeting_url is None
    assert iv.has_submitted_feedback is False
    assert iv.notetaker_transcript_id is None


def test_interview_full_round_trip():
    iv = AtsInterview(
        application_id="app-1",
        schedule_id="sched-1",
        event_id="evt-1",
        interview_id="interview-1",
        stage_id="stage-1",
        stage_name="Technical Screen",
        interview_title="System Design",
        scheduled_start="2026-06-20T17:00:00.000Z",
        scheduled_end="2026-06-20T18:00:00.000Z",
        status="Scheduled",
        interviewers=[
            AtsInterviewer(email="ada@example.com", name="Ada Lovelace", ats_user_id="user-1"),
        ],
        meeting_url="https://zoom.us/j/1",
        feedback_link="https://app.ashbyhq.com/feedback/evt-1",
        has_submitted_feedback=True,
        notetaker_transcript_id="nt-1",
    )
    assert iv.interviewers[0].name == "Ada Lovelace"
    assert iv.interviewers[0].ats_user_id == "user-1"
    assert iv.has_submitted_feedback is True


def test_interviewer_partial_fields():
    who = AtsInterviewer(email="x@y.co")
    assert who.email == "x@y.co"
    assert who.name is None
    assert who.ats_user_id is None


def test_transcript_defaults():
    t = AtsTranscript()
    assert t.text is None
    assert t.segments == []
    assert t.source is None
    assert t.raw is None
