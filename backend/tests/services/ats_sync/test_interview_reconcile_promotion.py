"""Reconcile loop → Phase C action handler (ongoing post-publish interviews).

After the per-application interview upserts, reconcile promotes interviews that
arrived AFTER publish: for each planned req of the org that has un-promoted
ats_interviews (candidate_round_id IS NULL), run ats_promote_interviews and
route the result to act_on_promoted_interviews. These tests cover the seam
(_promote_planned_req) and the discovery query that drives it.
"""

import pytest

from tests.helpers.mock_data import ORG_ID
from tests.helpers.supabase_mocks import mock_rpc, mock_select

from app.services.ats_sync import interview_reconcile
from app.services.supabase import get_supabase_admin_client

CONN = {
    "id": "conn-1",
    "organization_id": ORG_ID,
    "provider": "ashby",
    "knit_integration_id": "iid-1",
}


async def test_promote_planned_req_routes_to_action_handler(monkeypatch):
    captured = []

    async def _fake_act(supabase, promoted, *, bundle=None):
        captured.append((promoted, bundle))

    monkeypatch.setattr(
        interview_reconcile, "act_on_promoted_interviews", _fake_act
    )

    promoted = [
        {
            "candidate_round_id": "cr-9",
            "scheduled_start": "2099-01-01T00:00:00Z",
            "meeting_url": None,
            "notetaker_transcript_id": "nt-9",
            "status": "completed",
            "ats_interview_event_id": "evt-9",
            "organization_id": ORG_ID,
        }
    ]

    sentinel_bundle = object()
    await interview_reconcile._promote_planned_req(
        supabase=object(),
        requisition_id="req-9",
        organization_id=ORG_ID,
        bundle=sentinel_bundle,
        _promoted_override=promoted,
    )
    assert captured == [(promoted, sentinel_bundle)]


async def test_promote_planned_req_failure_is_soft(monkeypatch):
    async def _boom(supabase, promoted, *, bundle=None):
        raise RuntimeError("recall down")

    monkeypatch.setattr(interview_reconcile, "act_on_promoted_interviews", _boom)
    # must not raise
    await interview_reconcile._promote_planned_req(
        supabase=object(),
        requisition_id="req-9",
        organization_id=ORG_ID,
        bundle=object(),
        _promoted_override=[{"candidate_round_id": "cr-9"}],
    )


async def test_promote_un_promoted_discovers_planned_reqs(
    respx_mock, monkeypatch
):
    # un-promoted interview rows carry stage ids; the stage map links them to a
    # requisition; only the planned req is promoted.
    mock_select(
        respx_mock,
        "ats_interviews",
        [
            {"ats_stage_id": "st-1", "candidate_round_id": None},
            {"ats_stage_id": "st-2", "candidate_round_id": None},
            {"ats_stage_id": None, "candidate_round_id": None},  # ignored (no stage)
        ],
    )
    mock_select(
        respx_mock,
        "ats_stage_round_map",
        [
            {"requisition_id": "req-planned", "ats_stage_id": "st-1"},
            {"requisition_id": "req-draft", "ats_stage_id": "st-2"},
        ],
    )
    mock_select(
        respx_mock,
        "requisitions",
        [{"id": "req-planned", "status": "planned"}],  # only this one is planned
    )

    promoted_for = []

    async def _fake_promote_req(
        *, supabase, requisition_id, organization_id, bundle=None
    ):
        promoted_for.append(requisition_id)

    monkeypatch.setattr(
        interview_reconcile, "_promote_planned_req", _fake_promote_req
    )

    await interview_reconcile._promote_un_promoted_interviews(
        get_supabase_admin_client(), ORG_ID, bundle=object()
    )
    assert promoted_for == ["req-planned"]


async def test_promote_un_promoted_noop_when_nothing_unpromoted(
    respx_mock, monkeypatch
):
    mock_select(respx_mock, "ats_interviews", [])  # nothing un-promoted

    called = {"req": 0}

    async def _fake_promote_req(**_kw):
        called["req"] += 1

    monkeypatch.setattr(
        interview_reconcile, "_promote_planned_req", _fake_promote_req
    )
    await interview_reconcile._promote_un_promoted_interviews(
        get_supabase_admin_client(), ORG_ID, bundle=object()
    )
    assert called["req"] == 0


async def test_promote_planned_req_runs_rpc_when_no_override(
    respx_mock, monkeypatch
):
    # No override → the helper runs ats_promote_interviews via call_rpc and
    # routes its data to the action handler.
    mock_rpc(
        respx_mock,
        "ats_promote_interviews",
        [{"candidate_round_id": "cr-1", "organization_id": ORG_ID}],
    )

    captured = []

    async def _fake_act(supabase, promoted, *, bundle=None):
        captured.append(promoted)

    monkeypatch.setattr(
        interview_reconcile, "act_on_promoted_interviews", _fake_act
    )
    await interview_reconcile._promote_planned_req(
        supabase=get_supabase_admin_client(),
        requisition_id="req-1",
        organization_id=ORG_ID,
        bundle=object(),
    )
    assert captured == [[{"candidate_round_id": "cr-1", "organization_id": ORG_ID}]]
