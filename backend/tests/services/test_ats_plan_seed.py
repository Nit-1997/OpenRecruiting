"""filter_interview_stages: Ashby interviewStage.list rows -> seed rounds.

Live-confirmed stage shape: {id, title, type, orderInInterviewPlan, interviewPlanId,
interviewStageGroupId} where type in {Lead, PreInterviewScreen, Active, Offer, Hired,
Archived}. Only 'Active' stages are interview-bearing (the 4 real ones in the sandbox
are Recruiter Screen / Technical Phone Screen / Hiring Manager Phone Screen / Onsite)."""
from app.services.ats_sync.plan_seed import filter_interview_stages

STAGES = [
    {"id": "st_lead", "title": "Application Review", "type": "Lead", "orderInInterviewPlan": 0},
    {"id": "st_screen", "title": "Recruiter Screen", "type": "PreInterviewScreen", "orderInInterviewPlan": 1},
    {"id": "st_tech", "title": "Technical Interview", "type": "Active", "orderInInterviewPlan": 2},
    {"id": "st_onsite", "title": "Onsite Loop", "type": "Active", "orderInInterviewPlan": 3},
    {"id": "st_offer", "title": "Offer", "type": "Offer", "orderInInterviewPlan": 4},
    {"id": "st_hired", "title": "Hired", "type": "Hired", "orderInInterviewPlan": 5},
    {"id": "st_arch", "title": "Archived", "type": "Archived", "orderInInterviewPlan": 6},
]


def test_keeps_only_active_stages_in_order():
    rounds = filter_interview_stages(STAGES)
    assert [r["ats_stage_id"] for r in rounds] == ["st_tech", "st_onsite"]
    assert [r["name"] for r in rounds] == ["Technical Interview", "Onsite Loop"]
    assert [r["order"] for r in rounds] == [2, 3]
    assert rounds[0]["ats_stage_name"] == "Technical Interview"


def test_sorts_by_order_when_unsorted():
    unsorted = [
        {"id": "b", "title": "B", "type": "Active", "orderInInterviewPlan": 5},
        {"id": "a", "title": "A", "type": "Active", "orderInInterviewPlan": 1},
    ]
    rounds = filter_interview_stages(unsorted)
    assert [r["ats_stage_id"] for r in rounds] == ["a", "b"]


def test_empty_and_missing_type_safe():
    assert filter_interview_stages([]) == []
    assert filter_interview_stages([{"id": "x", "title": "X"}]) == []  # no type -> dropped
    assert filter_interview_stages([{"id": "x", "title": "X", "type": "Active"}])[0]["order"] == 0


def test_non_dict_entries_dropped():
    rows = ["junk", None, {"id": "ok", "title": "OK", "type": "Active", "orderInInterviewPlan": 1}]
    rounds = filter_interview_stages(rows)
    assert [r["ats_stage_id"] for r in rounds] == ["ok"]


# ---------------------------------------------------------------------------
# AtsInterviewStage canonical model (Correction 1)
# ---------------------------------------------------------------------------
def test_ats_interview_stage_model_round_trip():
    from app.integrations.ats.core.models import AtsInterviewStage

    s = AtsInterviewStage(
        stage_id="st_tech", title="Technical Interview", type="Active",
        order=2, interview_plan_id="plan-1",
    )
    assert s.stage_id == "st_tech"
    assert s.type == "Active"
    assert s.order == 2
    assert s.interview_plan_id == "plan-1"


def test_ats_interview_stage_model_minimal():
    from app.integrations.ats.core.models import AtsInterviewStage

    s = AtsInterviewStage(stage_id="st_x")
    assert s.stage_id == "st_x"
    assert s.title is None
    assert s.order == 0
    assert s.interview_plan_id is None


def test_filter_interview_stages_accepts_canonical_models():
    """fetch_job_stages returns AtsInterviewStage objects — the filter must
    accept those as well as raw Ashby dicts."""
    from app.integrations.ats.core.models import AtsInterviewStage

    stages = [
        AtsInterviewStage(stage_id="st_lead", title="Lead", type="Lead", order=0),
        AtsInterviewStage(stage_id="st_tech", title="Tech", type="Active", order=2),
        AtsInterviewStage(stage_id="st_screen", title="Screen", type="Active", order=1),
    ]
    rounds = filter_interview_stages(stages)
    assert [r["ats_stage_id"] for r in rounds] == ["st_screen", "st_tech"]
    assert [r["name"] for r in rounds] == ["Screen", "Tech"]


# ---------------------------------------------------------------------------
# fetch_seed_rounds — resolve the requisition's ATS job link, fetch stages via
# the provider bundle's interviews adapter, filter to interview-bearing. Best-
# effort: [] on no link / no connection / no adapter / adapter error.
# ---------------------------------------------------------------------------
import pytest  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from tests.helpers.mock_data import ORG_ID, REQ_ID  # noqa: E402
from tests.helpers.supabase_mocks import mock_select  # noqa: E402
from app.integrations.ats.core.models import AtsInterviewStage  # noqa: E402
from app.services.supabase import get_supabase_admin_client  # noqa: E402
from app.services.ats_sync import plan_seed  # noqa: E402

JOB_LINK = {"ats_id": "job_123", "native_id": REQ_ID, "native_type": "requisition", "ats_type": "job"}

_CANON_STAGES = [
    AtsInterviewStage(stage_id="st_lead", title="Lead", type="Lead", order=0),
    AtsInterviewStage(stage_id="st_tech", title="Technical Interview", type="Active", order=2),
    AtsInterviewStage(stage_id="st_onsite", title="Onsite Loop", type="Active", order=3),
]


@pytest.mark.asyncio
async def test_fetch_seed_rounds_returns_filtered(respx_mock, monkeypatch):
    mock_select(respx_mock, "ats_entity_links", [JOB_LINK])

    fake_interviews = MagicMock()
    fake_interviews.fetch_job_stages = AsyncMock(return_value=_CANON_STAGES)
    fake_bundle = MagicMock(interviews=fake_interviews)
    monkeypatch.setattr(plan_seed, "get_ats_provider", AsyncMock(return_value=fake_bundle))

    rounds = await plan_seed.fetch_seed_rounds(
        get_supabase_admin_client(), organization_id=ORG_ID, requisition_id=REQ_ID
    )
    assert [r["ats_stage_id"] for r in rounds] == ["st_tech", "st_onsite"]
    fake_interviews.fetch_job_stages.assert_awaited_once_with("job_123")


@pytest.mark.asyncio
async def test_fetch_seed_rounds_no_job_link_returns_empty(respx_mock, monkeypatch):
    mock_select(respx_mock, "ats_entity_links", [])  # no link row
    monkeypatch.setattr(plan_seed, "get_ats_provider", AsyncMock())
    rounds = await plan_seed.fetch_seed_rounds(
        get_supabase_admin_client(), organization_id=ORG_ID, requisition_id=REQ_ID
    )
    assert rounds == []
    plan_seed.get_ats_provider.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_seed_rounds_adapter_error_degrades(respx_mock, monkeypatch):
    mock_select(respx_mock, "ats_entity_links", [JOB_LINK])
    fake_interviews = MagicMock()
    fake_interviews.fetch_job_stages = AsyncMock(side_effect=RuntimeError("ashby 500"))
    monkeypatch.setattr(
        plan_seed, "get_ats_provider", AsyncMock(return_value=MagicMock(interviews=fake_interviews))
    )
    rounds = await plan_seed.fetch_seed_rounds(
        get_supabase_admin_client(), organization_id=ORG_ID, requisition_id=REQ_ID
    )
    assert rounds == []  # error swallowed -> no seeding


@pytest.mark.asyncio
async def test_fetch_seed_rounds_no_interviews_adapter_returns_empty(respx_mock, monkeypatch):
    mock_select(respx_mock, "ats_entity_links", [JOB_LINK])
    monkeypatch.setattr(
        plan_seed, "get_ats_provider", AsyncMock(return_value=MagicMock(interviews=None))
    )
    rounds = await plan_seed.fetch_seed_rounds(
        get_supabase_admin_client(), organization_id=ORG_ID, requisition_id=REQ_ID
    )
    assert rounds == []


@pytest.mark.asyncio
async def test_fetch_seed_rounds_not_connected_degrades(respx_mock, monkeypatch):
    from app.integrations.ats.core.errors import AtsNotConnectedError

    mock_select(respx_mock, "ats_entity_links", [JOB_LINK])
    monkeypatch.setattr(
        plan_seed, "get_ats_provider",
        AsyncMock(side_effect=AtsNotConnectedError("no active connection")),
    )
    rounds = await plan_seed.fetch_seed_rounds(
        get_supabase_admin_client(), organization_id=ORG_ID, requisition_id=REQ_ID
    )
    assert rounds == []
