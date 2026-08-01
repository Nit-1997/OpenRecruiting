"""Ashby InterviewsPort adapter + port conformance."""

from app.integrations.ats.core.ports import InterviewsPort


def test_interviews_port_is_runtime_checkable_protocol():
    # A trivial object with the three coroutine methods should satisfy the port.
    class _Stub:
        async def fetch_interviews(self, application_id):  # noqa: ANN001
            return []

        async def fetch_transcript(self, notetaker_transcript_id):  # noqa: ANN001
            return None

        async def fetch_job_stages(self, job_id):  # noqa: ANN001
            return []

    assert isinstance(_Stub(), InterviewsPort)


import pytest

from app.integrations.ats.passthrough.ashby.interviews import AshbyInterviewsAdapter


class _RecordingTransport:
    """Returns a canned body per (path) and records the calls made."""

    def __init__(self, by_path: dict):
        self._by_path = by_path
        self.calls: list[tuple[str, str, dict | None]] = []

    async def passthrough(self, integration_id, method, path, body=None):
        self.calls.append((method, path, body))
        return self._by_path.get(path, {})


def _schedule_body() -> dict:
    return {
        "success": True,
        "results": [
            {
                "id": "sched-1",
                "status": "Scheduled",
                "applicationId": "app-1",
                "interviewStageId": "stage-1",
                "interviewEvents": [
                    {
                        "id": "evt-1",
                        "interviewId": "interview-1",
                        "interviewers": [
                            {"id": "user-1", "firstName": "Ada", "lastName": "Lovelace",
                             "email": "ada@example.com"},
                        ],
                        "startTime": "2026-06-20T17:00:00.000Z",
                        "endTime": "2026-06-20T18:00:00.000Z",
                        "feedbackLink": "https://app.ashbyhq.com/feedback/evt-1",
                        "hasSubmittedFeedback": False,
                        "extraData": {},
                    }
                ],
            },
            {
                "id": "sched-2",
                "status": "Scheduled",
                "applicationId": "app-OTHER",   # must be filtered out client-side
                "interviewStageId": "stage-1",
                "interviewEvents": [
                    {"id": "evt-OTHER", "interviewId": "interview-1",
                     "interviewers": [], "startTime": None, "endTime": None}
                ],
            },
        ],
    }


def _plan_body() -> dict:
    # interviewStage.list requires interviewPlanId, so the adapter lists plans first.
    return {"success": True, "results": [
        {"id": "plan-1", "title": "Engineering Plan"},
    ]}


def _stage_body() -> dict:
    return {"success": True, "results": [
        {"id": "stage-1", "title": "Technical Screen", "type": "Active"},
    ]}


def _interview_body() -> dict:
    return {"success": True, "results": [
        {"id": "interview-1", "title": "System Design"},
    ]}


@pytest.mark.asyncio
async def test_fetch_interviews_filters_by_application_and_enriches():
    transport = _RecordingTransport({
        "/interviewSchedule.list": _schedule_body(),
        "/interviewPlan.list": _plan_body(),
        "/interviewStage.list": _stage_body(),
        "/interview.list": _interview_body(),
    })
    adapter = AshbyInterviewsAdapter(transport, "iid-1")
    out = await adapter.fetch_interviews("app-1")

    # only app-1's event survives the client-side filter
    assert [iv.event_id for iv in out] == ["evt-1"]
    iv = out[0]
    assert iv.stage_name == "Technical Screen"
    assert iv.interview_title == "System Design"
    assert iv.interviewers[0].email == "ada@example.com"

    # schedule.list called with {} (no confirmed app filter param)
    sched_calls = [c for c in transport.calls if c[1] == "/interviewSchedule.list"]
    assert sched_calls == [("POST", "/interviewSchedule.list", {})]
    # stages resolved via plan-list then stage-list-per-plan (interviewStage.list
    # REQUIRES interviewPlanId — verified live), interview titles via list-all.
    assert sum(1 for c in transport.calls if c[1] == "/interviewPlan.list") == 1
    stage_calls = [c for c in transport.calls if c[1] == "/interviewStage.list"]
    assert stage_calls == [("POST", "/interviewStage.list", {"interviewPlanId": "plan-1"})]
    assert sum(1 for c in transport.calls if c[1] == "/interview.list") == 1


@pytest.mark.asyncio
async def test_fetch_interviews_memoizes_catalogs_per_instance():
    # The reconcile sweep reuses ONE adapter instance per connection per tick and
    # calls fetch_interviews up to 100x. The static catalogs (interviewSchedule.list
    # + the stage/interview title maps) must be fetched ONCE on the instance and
    # reused, NOT re-fetched per call. Two calls on the SAME instance => exactly
    # one hit each to interviewSchedule.list / interviewPlan.list /
    # interviewStage.list / interview.list.
    transport = _RecordingTransport({
        "/interviewSchedule.list": _schedule_body(),
        "/interviewPlan.list": _plan_body(),
        "/interviewStage.list": _stage_body(),
        "/interview.list": _interview_body(),
    })
    adapter = AshbyInterviewsAdapter(transport, "iid-1")

    first = await adapter.fetch_interviews("app-1")
    # app-OTHER also has events in the canned body -> exercises a second call that
    # still resolves enrichment, proving the title maps (not just the schedule
    # list) are memoized.
    second = await adapter.fetch_interviews("app-OTHER")

    assert [iv.event_id for iv in first] == ["evt-1"]
    assert [iv.event_id for iv in second] == ["evt-OTHER"]

    def _count(path):
        return sum(1 for c in transport.calls if c[1] == path)

    assert _count("/interviewSchedule.list") == 1
    assert _count("/interviewPlan.list") == 1
    assert _count("/interviewStage.list") == 1
    assert _count("/interview.list") == 1


@pytest.mark.asyncio
async def test_fetch_interviews_no_match_returns_empty():
    transport = _RecordingTransport({
        "/interviewSchedule.list": _schedule_body(),
        "/interviewStage.list": _stage_body(),
        "/interview.list": _interview_body(),
    })
    adapter = AshbyInterviewsAdapter(transport, "iid-1")
    out = await adapter.fetch_interviews("app-DOES-NOT-EXIST")
    assert out == []


@pytest.mark.asyncio
async def test_fetch_interviews_empty_results_guard():
    transport = _RecordingTransport({"/interviewSchedule.list": {"results": None}})
    adapter = AshbyInterviewsAdapter(transport, "iid-1")
    out = await adapter.fetch_interviews("app-1")
    assert out == []
    # no enrichment calls when there are no matching schedules
    assert not any(
        c[1] in ("/interviewPlan.list", "/interviewStage.list", "/interview.list")
        for c in transport.calls
    )


@pytest.mark.asyncio
async def test_fetch_transcript_maps_present_transcript():
    transport = _RecordingTransport({
        "/notetakerTranscript.info": {
            "success": True,
            "results": {"transcript": [
                {"speaker": "Interviewer", "text": "Hello"},
                {"speaker": "Candidate", "text": "Hi"},
            ]},
        }
    })
    adapter = AshbyInterviewsAdapter(transport, "iid-1")
    t = await adapter.fetch_transcript("nt-1")
    assert t is not None
    assert t.source == "notetaker"
    assert len(t.segments) == 2
    assert transport.calls == [
        ("POST", "/notetakerTranscript.info", {"notetakerTranscriptId": "nt-1"})
    ]


@pytest.mark.asyncio
async def test_fetch_transcript_absent_returns_none():
    transport = _RecordingTransport({"/notetakerTranscript.info": {"results": {}}})
    adapter = AshbyInterviewsAdapter(transport, "iid-1")
    assert await adapter.fetch_transcript("nt-1") is None


# ---------------------------------------------------------------------------
# fetch_job_stages — job-scoped stage listing (Correction 1). interviewStage.list
# REQUIRES interviewPlanId, so the adapter resolves the job's plan id(s) via
# jobInterviewPlan.info (fallback job.info) FIRST, then lists each plan's stages.
# Live stage shape: {id, title, type, orderInInterviewPlan, interviewPlanId,
# interviewStageGroupId}.
# ---------------------------------------------------------------------------
def _job_plan_info_body() -> dict:
    # jobInterviewPlan.info {jobId} -> the job's interview plan(s).
    return {"success": True, "results": [{"id": "plan-7", "title": "SWE Plan"}]}


def _job_stage_list_body() -> dict:
    return {"success": True, "results": [
        {"id": "st_lead", "title": "Application Review", "type": "Lead",
         "orderInInterviewPlan": 0, "interviewPlanId": "plan-7"},
        {"id": "st_screen", "title": "Recruiter Screen", "type": "Active",
         "orderInInterviewPlan": 1, "interviewPlanId": "plan-7"},
        {"id": "st_tech", "title": "Technical Phone Screen", "type": "Active",
         "orderInInterviewPlan": 2, "interviewPlanId": "plan-7"},
    ]}


@pytest.mark.asyncio
async def test_fetch_job_stages_resolves_plan_then_lists_stages():
    transport = _RecordingTransport({
        "/jobInterviewPlan.info": _job_plan_info_body(),
        "/interviewStage.list": _job_stage_list_body(),
    })
    adapter = AshbyInterviewsAdapter(transport, "iid-1")
    stages = await adapter.fetch_job_stages("job-1")

    # All stages returned as AtsInterviewStage (filtering to Active happens in plan_seed).
    assert [s.stage_id for s in stages] == ["st_lead", "st_screen", "st_tech"]
    assert stages[1].type == "Active"
    assert stages[1].title == "Recruiter Screen"
    assert stages[1].order == 1
    assert stages[1].interview_plan_id == "plan-7"

    # Plan resolved by jobId, then stages listed with the resolved plan id.
    plan_calls = [c for c in transport.calls if c[1] == "/jobInterviewPlan.info"]
    assert plan_calls == [("POST", "/jobInterviewPlan.info", {"jobId": "job-1"})]
    stage_calls = [c for c in transport.calls if c[1] == "/interviewStage.list"]
    assert stage_calls == [("POST", "/interviewStage.list", {"interviewPlanId": "plan-7"})]


@pytest.mark.asyncio
async def test_fetch_job_stages_falls_back_to_job_info():
    # jobInterviewPlan.info yields nothing -> read plan ids from job.info.
    transport = _RecordingTransport({
        "/jobInterviewPlan.info": {"success": True, "results": []},
        "/job.info": {"success": True, "results": {
            "id": "job-1", "defaultInterviewPlanId": "plan-9",
            "interviewPlanIds": ["plan-9"],
        }},
        "/interviewStage.list": {"success": True, "results": [
            {"id": "st_a", "title": "Onsite", "type": "Active",
             "orderInInterviewPlan": 3, "interviewPlanId": "plan-9"},
        ]},
    })
    adapter = AshbyInterviewsAdapter(transport, "iid-1")
    stages = await adapter.fetch_job_stages("job-1")
    assert [s.stage_id for s in stages] == ["st_a"]
    assert stages[0].interview_plan_id == "plan-9"
    job_calls = [c for c in transport.calls if c[1] == "/job.info"]
    assert job_calls == [("POST", "/job.info", {"id": "job-1"})]


@pytest.mark.asyncio
async def test_fetch_job_stages_no_plan_returns_empty():
    transport = _RecordingTransport({
        "/jobInterviewPlan.info": {"success": True, "results": []},
        "/job.info": {"success": True, "results": {"id": "job-1"}},
    })
    adapter = AshbyInterviewsAdapter(transport, "iid-1")
    stages = await adapter.fetch_job_stages("job-1")
    assert stages == []
    # No stage listing attempted when no plan id resolves.
    assert not any(c[1] == "/interviewStage.list" for c in transport.calls)


@pytest.mark.asyncio
async def test_fetch_job_stages_dedupes_plan_ids():
    # Two plan refs to the same id -> stages listed once per unique plan.
    transport = _RecordingTransport({
        "/jobInterviewPlan.info": {"success": True, "results": [
            {"id": "plan-7"}, {"id": "plan-7"},
        ]},
        "/interviewStage.list": {"success": True, "results": [
            {"id": "st_tech", "title": "Tech", "type": "Active",
             "orderInInterviewPlan": 1, "interviewPlanId": "plan-7"},
        ]},
    })
    adapter = AshbyInterviewsAdapter(transport, "iid-1")
    stages = await adapter.fetch_job_stages("job-1")
    assert [s.stage_id for s in stages] == ["st_tech"]
    stage_calls = [c for c in transport.calls if c[1] == "/interviewStage.list"]
    assert len(stage_calls) == 1


# meeting_url_from_event — Ashby's real video-link field is `meetingLink` (camelCase),
# present only when a conferencing location is attached. Earlier code read
# location/meetingUrl but NOT meetingLink, so it missed real links.
from app.integrations.ats.passthrough.ashby.interviews_mapping import (  # noqa: E402
    meeting_url_from_event,
)


def test_meeting_url_reads_ashby_meetinglink():
    assert meeting_url_from_event({"meetingLink": "https://zoom.us/j/123"}) == "https://zoom.us/j/123"


def test_meeting_url_reads_location_object_and_string():
    assert meeting_url_from_event({"location": {"meetingLink": "https://meet.google.com/abc"}}) == "https://meet.google.com/abc"
    assert meeting_url_from_event({"location": "https://teams.microsoft.com/l/x"}) == "https://teams.microsoft.com/l/x"


def test_meeting_url_ignores_physical_location_and_empty():
    assert meeting_url_from_event({"location": "Conference Room A"}) is None
    assert meeting_url_from_event({"extraData": {}, "feedbackLink": "https://app.ashbyhq.com/x"}) is None
