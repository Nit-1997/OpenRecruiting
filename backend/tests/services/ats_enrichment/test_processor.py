"""process_candidate end-to-end with fake external boundaries + respx for the
supabase link/connection reads and the ats_enrich_candidate RPC."""

import json

from tests.helpers.supabase_mocks import mock_rpc, mock_select

from app.integrations.ats.core.models import (
    AtsApplication,
    AtsAttachment,
    AtsCandidate,
    AtsQuestionResponse,
    AtsRejection,
    AtsStageRef,
)
from app.services.ats_enrichment.processor import process_candidate
from app.services.ats_enrichment.profile_models import ResumeProfile
from app.services.supabase import get_supabase_admin_client

LINK = {
    "ats_id": "app1",
    "ats_candidate_id": "app1",
    "connection_id": "conn1",
    "organization_id": "org1",
    "provider": "workable",
}


def _app(with_resume=True):
    return AtsApplication(
        id="app1",
        status="REJECTED",
        candidate=AtsCandidate(id="app1", first_name="Nitin", location="Sunnyvale, CA"),
        applied_at="2026-06-12T20:33:28Z",
        current_stage=AtsStageRef(id="interview", name="Interview"),
        rejection=AtsRejection(reason="Doesn't have required experience", rejected_at="t"),
        question_responses=[AtsQuestionResponse(question="Need Visa", type="YES_NO", answer="NO")],
        attachments=(
            [AtsAttachment(type="RESUME", url="https://x/r.txt", name="r.txt")]
            if with_resume
            else []
        ),
    )


async def _fetch(_i, _a, _c):
    return _app()


async def _download(_url, _mb):
    return (b"Nitin Bhat\nSenior Engineer\nPython", "text/plain")


async def _extract(_text, _model):
    return ResumeProfile(summary="Senior Engineer", skills=["Python"])


def _upload(_data, _cid, _fn):
    return "https://durable/r.txt"


async def _push_ok(**_kwargs):
    return True


async def test_full_path_persists_profile_and_pushes(respx_mock):
    mock_select(respx_mock, "ats_entity_links", [LINK])
    mock_select(respx_mock, "ats_connections", [{"id": "conn1", "provider": "workable", "knit_integration_id": "int-1"}])
    mock_select(respx_mock, "requisitions", [{"role_title": "Senior Software Engineer", "status": "intake_pending"}])
    rpc = mock_rpc(respx_mock, "ats_enrich_candidate", {"updated": True})
    pushed: dict = {}

    async def _push(*, org_id, candidate_id, payload):
        pushed.update(payload)
        pushed["_org"] = org_id
        return True

    out = await process_candidate(
        get_supabase_admin_client(),
        {"id": "cand1", "requisition_id": "req1", "name": "Nitin", "status": "rejected", "profile": None},
        fetch_application=_fetch,
        download_resume=_download,
        extract_profile=_extract,
        upload_resume_fn=_upload,
        push_cortex=_push,
        model="resume-extract",
    )
    assert out == "done"
    sent = json.loads(rpc.calls[0].request.content)
    assert sent["p_candidate_id"] == "cand1" and sent["p_org_id"] == "org1"
    assert sent["p_resume_url"] == "https://durable/r.txt"
    prof = sent["p_profile"]
    assert prof["resume"]["summary"] == "Senior Engineer"
    assert prof["ats"]["location"] == "Sunnyvale, CA"
    assert prof["ats"]["rejection"]["reason"] == "Doesn't have required experience"
    assert prof["ats"]["screening_qa"][0]["answer"] == "NO"
    assert pushed["skills"] == ["Python"] and pushed["_org"] == "org1"
    # APPLIED_TO pipeline fields forwarded to cortex
    assert pushed["requisition_id"] == "req1"
    assert pushed["requisition_title"] == "Senior Software Engineer"


async def test_no_link_returns_skipped(respx_mock):
    mock_select(respx_mock, "ats_entity_links", [])
    out = await process_candidate(
        get_supabase_admin_client(),
        {"id": "candX", "profile": None},
        fetch_application=_fetch,
        push_cortex=_push_ok,
    )
    assert out == "skipped"


async def test_reenrichment_skips_download_and_llm(respx_mock):
    mock_select(respx_mock, "ats_entity_links", [LINK])
    mock_select(respx_mock, "ats_connections", [{"id": "conn1", "provider": "workable", "knit_integration_id": "int-1"}])
    mock_select(respx_mock, "requisitions", [{"role_title": "Senior Software Engineer", "status": "planned"}])
    rpc = mock_rpc(respx_mock, "ats_enrich_candidate", {"updated": True})

    async def _boom_dl(_url, _mb):
        raise AssertionError("must not download on re-enrichment")

    async def _boom_ex(_text, _model):
        raise AssertionError("must not run the LLM on re-enrichment")

    out = await process_candidate(
        get_supabase_admin_client(),
        {
            "id": "cand1",
            "requisition_id": "req1",
            "name": "N",
            "status": "rejected",
            "profile": {"resume": {"summary": "old summary", "skills": ["SQL"]}},
        },
        fetch_application=_fetch,
        download_resume=_boom_dl,
        extract_profile=_boom_ex,
        push_cortex=_push_ok,
    )
    assert out == "done"
    sent = json.loads(rpc.calls[0].request.content)
    # resume reused, ATS signals refreshed from the fresh pull
    assert sent["p_profile"]["resume"]["summary"] == "old summary"
    assert sent["p_profile"]["ats"]["rejection"]["reason"] == "Doesn't have required experience"


async def test_no_resume_attachment_profiles_ats_only(respx_mock):
    mock_select(respx_mock, "ats_entity_links", [LINK])
    mock_select(respx_mock, "ats_connections", [{"id": "conn1", "provider": "workable", "knit_integration_id": "int-1"}])
    mock_select(respx_mock, "requisitions", [{"role_title": "Senior Software Engineer", "status": "intake_pending"}])
    rpc = mock_rpc(respx_mock, "ats_enrich_candidate", {"updated": True})

    async def _fetch_no_resume(_i, _a, _c):
        return _app(with_resume=False)

    out = await process_candidate(
        get_supabase_admin_client(),
        {"id": "cand1", "requisition_id": "req1", "name": "N", "status": "active", "profile": None},
        fetch_application=_fetch_no_resume,
        push_cortex=_push_ok,
    )
    assert out == "done"
    sent = json.loads(rpc.calls[0].request.content)
    assert sent["p_profile"]["resume"] is None
    assert sent["p_resume_url"] is None
    assert sent["p_profile"]["source"] == "ats"


async def test_process_candidate_uses_registry_bundle_for_ashby(respx_mock, monkeypatch):
    from app.services.ats_enrichment import processor as proc

    called: dict = {}

    class _Candidates:
        @staticmethod
        async def get_application(app_id, cand_id):
            called["get_application"] = (app_id, cand_id)
            return AtsApplication(
                id=app_id,
                status="ACTIVE",
                candidate=AtsCandidate(id=cand_id),
                attachments=[AtsAttachment(type="RESUME", url="https://s3/r.pdf", name="r.pdf")],
            )

    class _Bundle:
        provider = "ashby"
        knit_integration_id = "iid-1"
        candidates = _Candidates()
        scorecards = None

    async def fake_get_ats_provider(supabase, org_id):
        called["org_id"] = org_id
        return _Bundle()

    monkeypatch.setattr(proc, "get_ats_provider", fake_get_ats_provider, raising=False)

    ashby_link = {
        "ats_id": "app-ashby",
        "ats_candidate_id": "cand-ashby",
        "connection_id": "conn1",
        "organization_id": "org1",
        "provider": "ashby",
    }
    mock_select(respx_mock, "ats_entity_links", [ashby_link])
    mock_select(respx_mock, "requisitions", [{"role_title": "Senior Software Engineer", "status": "intake_pending"}])
    mock_rpc(respx_mock, "ats_enrich_candidate", {"updated": True})

    out = await proc.process_candidate(
        get_supabase_admin_client(),
        {"id": "cand1", "requisition_id": "req1", "name": "Nitin", "status": "active", "profile": None},
        download_resume=_download,
        extract_profile=_extract,
        upload_resume_fn=_upload,
        push_cortex=_push_ok,
    )
    assert out == "done"
    assert called["org_id"] == "org1"
    assert called["get_application"] == ("app-ashby", "cand-ashby")


async def test_process_candidate_pushes_scorecards_when_supported(respx_mock, monkeypatch):
    from app.integrations.ats.core.models import AtsScorecard
    from app.services.ats_enrichment import processor as proc

    pushes: list = []

    async def fake_push_eval(*, org_id, candidate_id, payload):
        pushes.append({"org_id": org_id, "candidate_id": candidate_id, "payload": payload})
        return True

    monkeypatch.setattr(proc, "push_candidate_evaluation", fake_push_eval, raising=False)

    class _Candidates:
        @staticmethod
        async def get_application(app_id, cand_id):
            return AtsApplication(
                id=app_id,
                status="ACTIVE",
                candidate=AtsCandidate(id=cand_id),
                attachments=[AtsAttachment(type="RESUME", url="https://s3/r.pdf", name="r.pdf")],
            )

    class _Scorecards:
        @staticmethod
        async def fetch_scorecards(app_id, cand_id):
            return [AtsScorecard(id="fb1", interviewer_id="u1", recommendation=4)]

    class _Bundle:
        provider = "ashby"
        knit_integration_id = "iid-1"
        candidates = _Candidates()
        scorecards = _Scorecards()

    async def fake_get_ats_provider(supabase, org_id):
        return _Bundle()

    monkeypatch.setattr(proc, "get_ats_provider", fake_get_ats_provider, raising=False)

    ashby_link = {
        "ats_id": "app-ashby",
        "ats_candidate_id": "cand-ashby",
        "connection_id": "conn1",
        "organization_id": "org1",
        "provider": "ashby",
    }
    mock_select(respx_mock, "ats_entity_links", [ashby_link])
    mock_select(respx_mock, "requisitions", [{"role_title": "Senior Software Engineer", "status": "intake_pending"}])
    mock_rpc(respx_mock, "ats_enrich_candidate", {"updated": True})

    out = await proc.process_candidate(
        get_supabase_admin_client(),
        {"id": "cand1", "requisition_id": "req1", "name": "Nitin", "status": "active", "profile": None},
        download_resume=_download,
        extract_profile=_extract,
        upload_resume_fn=_upload,
        push_cortex=_push_ok,
    )
    assert out == "done"
    assert pushes, "candidate_evaluation must be pushed when scorecards are returned"
    assert pushes[0]["candidate_id"] == "cand1"
    assert pushes[0]["org_id"] == "org1"
    assert pushes[0]["payload"]["candidate_id"] == "cand1"
    assert pushes[0]["payload"]["evaluations"][0]["recommendation"] == "strong_yes"
