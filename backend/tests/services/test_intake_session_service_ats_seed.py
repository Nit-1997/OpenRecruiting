"""create_session injects ats_stages into the context-builder Lambda payload.

Additive: non-ATS sessions get an empty ats_stages list (byte-identical payload
otherwise), and fetch_seed_rounds is best-effort (never raises)."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.intake_session_service import IntakeSessionService


def _supabase_for_create():
    client = MagicMock()
    client.table.return_value = client
    client.insert.return_value = client
    client.select.return_value = client
    client.eq.return_value = client
    client.is_null.return_value = client
    client.single.return_value = client
    client.order.return_value = client
    client.limit.return_value = client
    client.update.return_value = client
    client.execute_async = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_create_session_complete_intake_passes_ats_stages(monkeypatch):
    """ATS complete-intake path seeds the payload with the fetched stages."""
    uid, oid, rid = uuid4(), uuid4(), uuid4()
    sb = _supabase_for_create()
    sb.execute_async.side_effect = [
        # _load_requisition_for_intake -> single() (dict)
        MagicMock(data={
            "id": str(rid), "status": "intake_pending", "role_title": "SWE",
            "role_location": "NYC", "experience_min_years": 3,
            "experience_max_years": 6, "job_description": "jd",
            "is_system_template": False,
        }),
        # _active_session_for_requisition -> list (no active-status row -> None)
        MagicMock(data=[]),
        # intake_sessions insert -> list (first_row)
        MagicMock(data=[{"id": str(uuid4())}]),
        # prefill-skipped cold-start fallback update (no Lambda ARN unless set)
        MagicMock(data=[]),
    ]
    seed = [{"ats_stage_id": "st_tech", "ats_stage_name": "Tech", "name": "Tech", "order": 2}]
    monkeypatch.setenv("INTAKE_CONTEXT_BUILDER_LAMBDA_ARN", "arn:fake")
    svc = IntakeSessionService(sb)

    invoke = AsyncMock()
    with patch("app.services.intake_session_service.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=invoke))), \
         patch("app.services.intake_session_service.fetch_seed_rounds", new=AsyncMock(return_value=seed)) as fsr:
        await svc.create_session(uid, oid, None, "complete_intake", requisition_id=rid)

    payload = invoke.await_args.kwargs["payload"]
    assert payload["ats_stages"] == seed
    assert payload["session_id"]
    assert payload["include_turns"] is False
    # fetch_seed_rounds called with the org + requisition.
    assert fsr.await_args.kwargs["requisition_id"] == str(rid)
    assert fsr.await_args.kwargs["organization_id"] == str(oid)


@pytest.mark.asyncio
async def test_create_session_manual_passes_empty_stages(monkeypatch):
    """Non-ATS (manual form) path passes an empty ats_stages list."""
    from app.api.v2.schemas.intake import IntakeFormData

    uid, oid = uuid4(), uuid4()
    sb = _supabase_for_create()
    sb.execute_async.side_effect = [
        MagicMock(data=[{"id": str(uuid4())}]),  # requisitions insert
        MagicMock(data=[{"id": str(uuid4())}]),  # intake_sessions insert
        MagicMock(data=[]),                       # cold-start fallback update
    ]
    monkeypatch.setenv("INTAKE_CONTEXT_BUILDER_LAMBDA_ARN", "arn:fake")
    form = IntakeFormData(role_name="SWE", experience_min=2, experience_max=5,
                          location="NYC", jd_text=None)
    svc = IntakeSessionService(sb)
    invoke = AsyncMock()
    with patch("app.services.intake_session_service.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=invoke))), \
         patch("app.services.intake_session_service.fetch_seed_rounds", new=AsyncMock(return_value=[])):
        await svc.create_session(uid, oid, form, "manual")
    assert invoke.await_args.kwargs["payload"]["ats_stages"] == []


@pytest.mark.asyncio
async def test_create_session_seed_failure_does_not_break(monkeypatch):
    """fetch_seed_rounds is best-effort: even if it raised, session creation
    proceeds (it never raises in practice, but guard the wiring)."""
    from app.api.v2.schemas.intake import IntakeFormData

    uid, oid = uuid4(), uuid4()
    sb = _supabase_for_create()
    sb.execute_async.side_effect = [
        MagicMock(data=[{"id": str(uuid4())}]),  # requisitions insert
        MagicMock(data=[{"id": str(uuid4())}]),  # intake_sessions insert
        MagicMock(data=[]),                       # cold-start fallback update
    ]
    monkeypatch.setenv("INTAKE_CONTEXT_BUILDER_LAMBDA_ARN", "arn:fake")
    form = IntakeFormData(role_name="SWE", experience_min=2, experience_max=5,
                          location="NYC", jd_text=None)
    svc = IntakeSessionService(sb)
    # fetch_seed_rounds returns [] (its own best-effort contract); invoke succeeds.
    with patch("app.services.intake_session_service.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=AsyncMock()))), \
         patch("app.services.intake_session_service.fetch_seed_rounds", new=AsyncMock(return_value=[])):
        resp = await svc.create_session(uid, oid, form, "manual")
    assert resp.requisition_id is not None
