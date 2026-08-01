"""Canonical interview/transcript models — provider-agnostic shapes consumers see.
One row of `ats_interviews` maps to one AtsInterview (per Ashby interview EVENT)."""

from pydantic import BaseModel, Field


class AtsInterviewer(BaseModel):
    email: str | None = None
    name: str | None = None
    ats_user_id: str | None = None


class AtsInterview(BaseModel):
    application_id: str | None = None
    schedule_id: str | None = None
    event_id: str
    interview_id: str | None = None
    stage_id: str | None = None
    stage_name: str | None = None
    interview_title: str | None = None
    scheduled_start: str | None = None
    scheduled_end: str | None = None
    status: str | None = None
    interviewers: list[AtsInterviewer] = Field(default_factory=list)
    meeting_url: str | None = None
    feedback_link: str | None = None
    has_submitted_feedback: bool = False
    notetaker_transcript_id: str | None = None


class AtsTranscript(BaseModel):
    text: str | None = None
    segments: list[dict] = Field(default_factory=list)  # [{speaker, text}, ...]
    source: str | None = None  # notetaker | recall
    raw: dict | None = None


class AtsInterviewStage(BaseModel):
    """One Ashby interviewStage.list row. `type` in {Lead, PreInterviewScreen,
    Active, Offer, Hired, Archived} — only 'Active' is interview-bearing (used to
    seed the OpenRecruiting plan)."""

    stage_id: str
    title: str | None = None
    type: str | None = None
    order: int = 0
    interview_plan_id: str | None = None
