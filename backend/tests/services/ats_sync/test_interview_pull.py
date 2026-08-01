"""pull_interviews_for_application: bundle.interviews.fetch_interviews → one
ats_upsert_interview RPC per event. Idempotent by construction (RPC keyed on
event id); the same event mapped twice still issues one RPC per fetched event."""

import json

from tests.helpers.mock_data import ORG_ID
from tests.helpers.supabase_mocks import mock_rpc

from app.integrations.ats.core.models import AtsInterview, AtsInterviewer
from app.services.ats_sync.interview_pull import pull_interviews_for_application
from app.services.supabase import get_supabase_admin_client


class _Bundle:
    def __init__(self, interviews_adapter):
        self.connection_id = "conn-1"
        self.provider = "ashby"
        self.knit_integration_id = "iid-1"
        self.interviews = interviews_adapter


class _FakeInterviews:
    def __init__(self, out):
        self._out = out
        self.calls: list[str] = []

    async def fetch_interviews(self, application_id):
        self.calls.append(application_id)
        return self._out


def _interview(event_id="evt-1") -> AtsInterview:
    return AtsInterview(
        application_id="app-1",
        schedule_id="sched-1",
        event_id=event_id,
        interview_id="interview-1",
        stage_id="stage-1",
        stage_name="Technical Screen",
        interview_title="System Design",
        scheduled_start="2026-06-20T17:00:00.000Z",
        scheduled_end="2026-06-20T18:00:00.000Z",
        status="Scheduled",
        interviewers=[AtsInterviewer(email="ada@example.com", name="Ada Lovelace", ats_user_id="user-1")],
        feedback_link="https://app.ashbyhq.com/feedback/evt-1",
        has_submitted_feedback=False,
    )


async def test_pulls_and_upserts_each_event(respx_mock):
    rpc = mock_rpc(respx_mock, "ats_upsert_interview", {"action": "inserted", "id": "row-1"})
    adapter = _FakeInterviews([_interview("evt-1"), _interview("evt-2")])
    bundle = _Bundle(adapter)

    n = await pull_interviews_for_application(
        get_supabase_admin_client(), bundle, ORG_ID, "app-1"
    )

    assert n == 2
    assert adapter.calls == ["app-1"]
    assert rpc.call_count == 2
    sent = json.loads(rpc.calls[0].request.content)
    assert sent["p_org"] == ORG_ID
    assert sent["p_connection"] == "conn-1"
    f = sent["p_fields"]
    assert f["ats_interview_event_id"] == "evt-1"
    assert f["ats_application_id"] == "app-1"
    assert f["stage_name"] == "Technical Screen"
    assert f["interview_title"] == "System Design"
    assert f["status"] == "Scheduled"
    assert f["provider"] == "ashby"
    assert f["interviewers"] == [
        {"email": "ada@example.com", "name": "Ada Lovelace", "ats_user_id": "user-1"}
    ]


async def test_no_interviews_makes_no_rpc(respx_mock):
    rpc = mock_rpc(respx_mock, "ats_upsert_interview", {"action": "inserted", "id": "x"})
    bundle = _Bundle(_FakeInterviews([]))
    n = await pull_interviews_for_application(
        get_supabase_admin_client(), bundle, ORG_ID, "app-1"
    )
    assert n == 0
    assert rpc.call_count == 0


async def test_no_interviews_adapter_is_noop(respx_mock):
    # provider without a native interviews adapter (bundle.interviews is None)
    bundle = _Bundle(None)
    n = await pull_interviews_for_application(
        get_supabase_admin_client(), bundle, ORG_ID, "app-1"
    )
    assert n == 0
