"""Tests for IntakeSessionService."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.api.v2.schemas.intake import IntakeFormData
from app.services.intake_session_service import IntakeSessionService


@pytest.fixture(autouse=True)
def _no_ats_seed():
    """create_session now best-effort-fetches Ashby interview stages for the
    plan-seeding payload (spec §8). These pre-ATS tests assert exact DB-call
    sequences, so stub the seed fetch to [] (its real no-ATS-link result) to keep
    it off the supabase mock. ATS seeding is covered in
    test_intake_session_service_ats_seed.py."""
    with patch(
        "app.services.intake_session_service.fetch_seed_rounds",
        new=AsyncMock(return_value=[]),
    ):
        yield


@pytest.fixture(autouse=True)
def _no_credit_charge():
    """create_session charges an intake credit before writing. It goes through
    the admin supabase client rather than the injected mock, so stub it out for
    the tests that assert exact DB-call sequences. Metering itself is covered by
    test_create_session_charges_intake_credit and the resume test below."""
    with patch(
        "app.services.intake_session_service.use_credit",
        new=AsyncMock(),
    ) as uc:
        yield uc


@pytest.fixture
def mock_supabase():
    client = MagicMock()
    client.table.return_value = client
    client.insert.return_value = client
    client.update.return_value = client
    client.eq.return_value = client
    client.execute_async = AsyncMock()
    return client


@pytest.fixture
def service(mock_supabase):
    s = IntakeSessionService(supabase_client=mock_supabase)
    return s


@pytest.mark.asyncio
async def test_create_session_inserts_requisition_first(service, mock_supabase, monkeypatch):
    monkeypatch.setenv("INTAKE_CONTEXT_BUILDER_LAMBDA_ARN", "arn:aws:lambda:us-west-1:111:function:test")
    user_id = uuid4()
    org_id = uuid4()
    req_id = uuid4()
    session_id = uuid4()
    mock_supabase.execute_async.side_effect = [
        MagicMock(data=[{"id": str(req_id)}]),    # requisition insert
        MagicMock(data=[{"id": str(session_id)}]),  # session insert
    ]
    form_data = IntakeFormData(
        role_name="Senior BE", experience_min=5, experience_max=8,
        location="NYC", jd_text=None,
    )
    invoke = AsyncMock()
    with patch("app.services.intake_session_service.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=invoke))):
        result = await service.create_session(
            user_id=user_id, org_id=org_id, form_data=form_data, entry_point="create_role_btn",
        )
    assert result.requisition_id == req_id
    assert result.session_id == session_id
    invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_session_cold_starts_when_prefill_unavailable(service, mock_supabase, monkeypatch):
    """Prefill is best-effort. When no context-builder is reachable the session is
    still created and transitioned to 'ready' with empty answers, so the recruiter
    can start straight away."""
    session_id = uuid4()
    mock_supabase.execute_async.side_effect = [
        MagicMock(data=[{"id": str(uuid4())}]),   # requisition insert
        MagicMock(data=[{"id": str(session_id)}]),  # session insert
        MagicMock(data=[{"id": str(session_id)}]),  # cold-start ready update
    ]
    form_data = IntakeFormData(role_name="x", experience_min=1, experience_max=2, location="x")
    unavailable = MagicMock(return_value=MagicMock(
        invoke=AsyncMock(side_effect=RuntimeError("no context builder configured"))))
    with patch("app.services.intake_session_service.get_invoker", new=unavailable):
        await service.create_session(user_id=uuid4(), org_id=uuid4(), form_data=form_data, entry_point=None)
    # Session must be transitioned to ready with empty answers
    mock_supabase.update.assert_called_once()
    update_payload = mock_supabase.update.call_args.args[0]
    assert update_payload["status"] == "ready"
    assert len(update_payload["prefilled_answers"]) == 9
    assert len(update_payload["current_answers"]) == 9
    first_answer = next(iter(update_payload["prefilled_answers"].values()))
    assert first_answer == {"text": None, "extraction_confidence": "none", "sources": []}


@pytest.mark.asyncio
async def test_create_session_marks_ready_on_lambda_invoke_failure(service, mock_supabase, monkeypatch):
    monkeypatch.setenv("INTAKE_CONTEXT_BUILDER_LAMBDA_ARN", "arn:aws:lambda:us-west-1:111:function:test")
    session_id = uuid4()
    mock_supabase.execute_async.side_effect = [
        MagicMock(data=[{"id": str(uuid4())}]),   # requisition insert
        MagicMock(data=[{"id": str(session_id)}]),  # session insert
        MagicMock(data=[{"id": str(session_id)}]),  # cold-start ready update
    ]
    form_data = IntakeFormData(role_name="x", experience_min=1, experience_max=2, location="x")
    with patch(
        "app.services.intake_session_service.get_invoker",
        new=MagicMock(return_value=MagicMock(
            invoke=AsyncMock(side_effect=RuntimeError("worker unreachable")))),
    ):
        await service.create_session(user_id=uuid4(), org_id=uuid4(), form_data=form_data, entry_point=None)
    # Session must be marked ready despite the invoke failure
    mock_supabase.update.assert_called_once()
    update_payload = mock_supabase.update.call_args.args[0]
    assert update_payload["status"] == "ready"
    assert len(update_payload["prefilled_answers"]) == 9
    assert len(update_payload["current_answers"]) == 9


@pytest.mark.asyncio
async def test_create_session_uses_questions_snapshot(service, mock_supabase, monkeypatch):
    from intake_core.questions import QUESTIONS_VERSION, snapshot_questions
    monkeypatch.setenv("INTAKE_CONTEXT_BUILDER_LAMBDA_ARN", "arn:aws:lambda:us-west-1:111:function:test")
    mock_supabase.execute_async.side_effect = [
        MagicMock(data=[{"id": str(uuid4())}]),
        MagicMock(data=[{"id": str(uuid4())}]),
    ]
    form_data = IntakeFormData(
        role_name="x", experience_min=1, experience_max=2, location="x",
    )
    with patch("app.services.intake_session_service.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=AsyncMock()))):
        await service.create_session(
            user_id=uuid4(), org_id=uuid4(), form_data=form_data, entry_point=None,
        )
    # Second .insert call is for intake_sessions
    insert_calls = [c for c in mock_supabase.insert.call_args_list]
    assert len(insert_calls) == 2
    session_insert = insert_calls[1].args[0]
    assert session_insert["questions_version"] == QUESTIONS_VERSION
    assert len(session_insert["questions_snapshot"]) == 9


@pytest.mark.asyncio
async def test_create_session_open_ended_max_inserts_null(service, mock_supabase, monkeypatch):
    """A blank/None max ("X+ years") must insert NULL — never 0 — so the
    requisitions valid_experience CHECK is satisfied even when min > 0."""
    monkeypatch.setenv("INTAKE_CONTEXT_BUILDER_LAMBDA_ARN", "arn:aws:lambda:us-west-1:111:function:test")
    mock_supabase.execute_async.side_effect = [
        MagicMock(data=[{"id": str(uuid4())}]),   # requisition insert
        MagicMock(data=[{"id": str(uuid4())}]),   # session insert
    ]
    form_data = IntakeFormData(
        role_name="Staff Eng", experience_min=7, experience_max=None, location="Remote",
    )
    with patch("app.services.intake_session_service.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=AsyncMock()))):
        await service.create_session(
            user_id=uuid4(), org_id=uuid4(), form_data=form_data, entry_point="create_role_btn",
        )
    req_insert = mock_supabase.insert.call_args_list[0].args[0]
    assert req_insert["experience_min_years"] == 7
    assert req_insert["experience_max_years"] is None


@pytest.mark.asyncio
async def test_create_session_rejects_max_below_min(service, mock_supabase):
    """An explicit max < min returns a clean ValidationError (400) before any
    DB write — not a raw 23514 check_violation leaked to the user."""
    from app.api.v2.core.exceptions import ValidationError

    form_data = IntakeFormData(
        role_name="x", experience_min=7, experience_max=3, location="x",
    )
    with pytest.raises(ValidationError):
        await service.create_session(
            user_id=uuid4(), org_id=uuid4(), form_data=form_data, entry_point=None,
        )
    # Must fail before touching the DB.
    mock_supabase.insert.assert_not_called()


@pytest.mark.asyncio
async def test_get_session_loads_row(service, mock_supabase):
    sid = uuid4()
    uid = uuid4()
    oid = uuid4()
    expected_row = {
        "id": str(sid), "requisition_id": str(uuid4()), "user_id": str(uid),
        "organization_id": str(oid), "status": "created",
        "form_data": {"role_name": "x"}, "questions_version": "v1",
        "questions_snapshot": [], "turns": [], "process_stages": [],
        "process_status": "idle", "modalities_used": [],
        "created_at": "2026-05-27T00:00:00Z", "updated_at": "2026-05-27T00:00:00Z",
    }
    mock_supabase.select.return_value = mock_supabase
    mock_supabase.single.return_value = mock_supabase
    mock_supabase.execute_async.return_value = MagicMock(data=expected_row)
    result = await service.get_session(session_id=sid, user_id=uid, organization_id=oid)
    assert result.id == sid


@pytest.mark.asyncio
async def test_get_session_cross_tenant_returns_lookup_error(service, mock_supabase):
    """Querying with wrong org/user returns no row — service raises LookupError (→ 404)."""
    sid = uuid4()
    mock_supabase.select.return_value = mock_supabase
    mock_supabase.single.return_value = mock_supabase
    # Simulate Supabase returning no data when the WHERE filters don't match
    mock_supabase.execute_async.return_value = MagicMock(data=None)
    with pytest.raises(LookupError):
        await service.get_session(session_id=sid, user_id=uuid4(), organization_id=uuid4())


@pytest.mark.asyncio
async def test_create_session_dict_data_shape(service, mock_supabase, monkeypatch):
    """SupabaseAdminClient.InsertBuilder.execute_async() returns .data as dict (not list).
    first_row must handle this so create_session doesn't crash with TypeError."""
    monkeypatch.setenv("INTAKE_CONTEXT_BUILDER_LAMBDA_ARN", "arn:aws:lambda:us-west-1:111:function:test")
    req_id = uuid4()
    session_id = uuid4()
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(req_id)}),       # dict shape — production SupabaseAdminClient
        MagicMock(data={"id": str(session_id)}),   # dict shape — production SupabaseAdminClient
    ]
    form_data = IntakeFormData(
        role_name="Staff Eng", experience_min=7, experience_max=10,
        location="Remote", jd_text=None,
    )
    with patch("app.services.intake_session_service.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=AsyncMock()))):
        result = await service.create_session(
            user_id=uuid4(), org_id=uuid4(), form_data=form_data, entry_point=None,
        )
    assert result.requisition_id == req_id
    assert result.session_id == session_id


@pytest.mark.asyncio
async def test_create_session_raises_when_req_insert_returns_empty(service, mock_supabase, monkeypatch):
    """If the requisition insert returns None/empty, RuntimeError is raised immediately."""
    monkeypatch.setenv("INTAKE_CONTEXT_BUILDER_LAMBDA_ARN", "arn:aws:lambda:us-west-1:111:function:test")
    mock_supabase.execute_async.side_effect = [
        MagicMock(data=None),   # failed insert — no row returned
    ]
    form_data = IntakeFormData(role_name="x", experience_min=1, experience_max=2, location="x")
    with pytest.raises(RuntimeError, match="Requisition insert returned no data"):
        await service.create_session(user_id=uuid4(), org_id=uuid4(), form_data=form_data, entry_point=None)


@pytest.mark.asyncio
async def test_create_session_raises_when_session_insert_returns_empty(service, mock_supabase, monkeypatch):
    """If the session insert returns None/empty, RuntimeError is raised."""
    monkeypatch.setenv("INTAKE_CONTEXT_BUILDER_LAMBDA_ARN", "arn:aws:lambda:us-west-1:111:function:test")
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(uuid4())}),   # req insert succeeds (dict shape)
        MagicMock(data=None),                    # session insert fails
    ]
    form_data = IntakeFormData(role_name="x", experience_min=1, experience_max=2, location="x")
    with pytest.raises(RuntimeError, match="Session insert returned no data"):
        await service.create_session(user_id=uuid4(), org_id=uuid4(), form_data=form_data, entry_point=None)


# ---------------------------------------------------------------------------
# Complete-intake path: create_session(requisition_id=...) attaches/resumes
# ---------------------------------------------------------------------------


def _wire_read_chain(mock_supabase):
    """The attach path reads requisitions + intake_sessions before inserting."""
    for method in ("select", "is_null", "single", "order", "limit"):
        getattr(mock_supabase, method).return_value = mock_supabase


def _req_row(req_id, **overrides):
    row = {
        "id": str(req_id),
        "status": "intake_pending",
        "role_title": "Director of Finance",
        "role_location": "San Francisco",
        "experience_min_years": 8,
        "experience_max_years": 12,
        "job_description": "Own the finance org.",
        "is_system_template": False,
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_create_session_for_existing_requisition_attaches(service, mock_supabase, monkeypatch):
    """requisition_id path: no requisition INSERT; the session row points at
    the existing req and form_data is seeded from the requisition fields."""
    monkeypatch.setenv("INTAKE_CONTEXT_BUILDER_LAMBDA_ARN", "arn:aws:lambda:us-west-1:111:function:test")
    _wire_read_chain(mock_supabase)
    req_id = uuid4()
    session_id = uuid4()
    mock_supabase.execute_async.side_effect = [
        MagicMock(data=_req_row(req_id)),           # requisition load (.single)
        MagicMock(data=[]),                         # no active sessions
        MagicMock(data=[{"id": str(session_id)}]),  # session insert
    ]
    with patch("app.services.intake_session_service.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=AsyncMock()))):
        result = await service.create_session(
            user_id=uuid4(), org_id=uuid4(), form_data=None,
            entry_point="complete_intake_btn", requisition_id=req_id,
        )
    assert result.requisition_id == req_id
    assert result.session_id == session_id
    mock_supabase.insert.assert_called_once()  # session only — no new requisition
    session_insert = mock_supabase.insert.call_args.args[0]
    assert session_insert["requisition_id"] == str(req_id)
    assert session_insert["form_data"]["role_name"] == "Director of Finance"
    assert session_insert["form_data"]["jd_text"] == "Own the finance org."
    assert session_insert["entry_point"] == "complete_intake_btn"


@pytest.mark.asyncio
async def test_create_session_resumes_callers_active_session(service, mock_supabase):
    """An active session for the role (same user) is returned, not duplicated."""
    _wire_read_chain(mock_supabase)
    user_id = uuid4()
    req_id = uuid4()
    existing_sid = uuid4()
    mock_supabase.execute_async.side_effect = [
        MagicMock(data=_req_row(req_id)),
        MagicMock(data=[
            {"id": str(existing_sid), "user_id": str(user_id), "status": "submitted"},
            {"id": str(uuid4()), "user_id": str(user_id), "status": "abandoned"},
        ]),
    ]
    result = await service.create_session(
        user_id=user_id, org_id=uuid4(), form_data=None,
        entry_point="complete_intake_btn", requisition_id=req_id,
    )
    assert result.session_id == existing_sid
    assert result.requisition_id == req_id
    mock_supabase.insert.assert_not_called()


@pytest.mark.asyncio
async def test_create_session_conflicts_on_teammates_active_session(service, mock_supabase):
    from app.api.v2.core.exceptions import ConflictError

    _wire_read_chain(mock_supabase)
    req_id = uuid4()
    mock_supabase.execute_async.side_effect = [
        MagicMock(data=_req_row(req_id)),
        MagicMock(data=[{"id": str(uuid4()), "user_id": str(uuid4()), "status": "active"}]),
    ]
    with pytest.raises(ConflictError) as exc:
        await service.create_session(
            user_id=uuid4(), org_id=uuid4(), form_data=None,
            entry_point=None, requisition_id=req_id,
        )
    assert exc.value.code == "INTAKE_IN_PROGRESS"
    mock_supabase.insert.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("req_status", "expected_code"),
    [("closed", "REQ_CLOSED"), ("planned", "INTAKE_ALREADY_COMPLETE")],
)
async def test_create_session_rejects_non_pending_requisition(
    service, mock_supabase, req_status, expected_code
):
    from app.api.v2.core.exceptions import ConflictError

    _wire_read_chain(mock_supabase)
    mock_supabase.execute_async.side_effect = [
        MagicMock(data=_req_row(uuid4(), status=req_status)),
    ]
    with pytest.raises(ConflictError) as exc:
        await service.create_session(
            user_id=uuid4(), org_id=uuid4(), form_data=None,
            entry_point=None, requisition_id=uuid4(),
        )
    assert exc.value.code == expected_code
    mock_supabase.insert.assert_not_called()


@pytest.mark.asyncio
async def test_create_session_requisition_not_found(service, mock_supabase):
    from app.api.v2.core.exceptions import NotFoundError

    _wire_read_chain(mock_supabase)
    mock_supabase.execute_async.side_effect = [MagicMock(data=None)]
    with pytest.raises(NotFoundError):
        await service.create_session(
            user_id=uuid4(), org_id=uuid4(), form_data=None,
            entry_point=None, requisition_id=uuid4(),
        )
    mock_supabase.insert.assert_not_called()


def test_form_data_from_requisition_clamps_imported_values():
    """ATS rows can carry sparse/out-of-range fields — seeding must not fail."""
    from app.services.intake_session_service import _form_data_from_requisition

    form = _form_data_from_requisition({
        "role_title": None,
        "role_location": "  ",
        "experience_min_years": 80,
        "experience_max_years": 3,
        "job_description": None,
    })
    assert form.role_name == "Imported role"
    assert form.location == "Not specified"
    assert form.experience_min == 50      # clamped to the schema ceiling
    assert form.experience_max is None    # 3 < clamped min → dropped
    assert form.jd_text is None


# --------------------------- credit metering ---------------------------


@pytest.mark.asyncio
async def test_create_session_charges_intake_credit(
    service, mock_supabase, monkeypatch, _no_credit_charge
):
    """A new intake consumes one of the org's intake credits."""
    monkeypatch.setenv("INTAKE_CONTEXT_BUILDER_LAMBDA_ARN", "arn:aws:lambda:us-west-1:111:function:test")
    org_id = uuid4()
    mock_supabase.execute_async.side_effect = [
        MagicMock(data=[{"id": str(uuid4())}]),
        MagicMock(data=[{"id": str(uuid4())}]),
    ]
    form_data = IntakeFormData(
        role_name="Senior BE", experience_min=5, experience_max=8,
        location="NYC", jd_text=None,
    )
    with patch("app.services.intake_session_service.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=AsyncMock()))):
        await service.create_session(
            user_id=uuid4(), org_id=org_id, form_data=form_data, entry_point="manual",
        )

    _no_credit_charge.assert_awaited_once_with(str(org_id), "intake")


@pytest.mark.asyncio
async def test_create_session_charges_before_writing_anything(
    service, mock_supabase, _no_credit_charge
):
    """An exhausted org gets a 402 and leaves no orphaned draft requisition."""
    from fastapi import HTTPException

    _no_credit_charge.side_effect = HTTPException(status_code=402, detail="exhausted")
    form_data = IntakeFormData(
        role_name="Senior BE", experience_min=5, experience_max=8,
        location="NYC", jd_text=None,
    )
    with pytest.raises(HTTPException) as e:
        await service.create_session(
            user_id=uuid4(), org_id=uuid4(), form_data=form_data, entry_point="manual",
        )

    assert e.value.status_code == 402
    mock_supabase.insert.assert_not_called()


@pytest.mark.asyncio
async def test_resuming_an_active_session_is_free(service, mock_supabase, _no_credit_charge):
    """Reopening an in-progress intake must not charge again."""
    _wire_read_chain(mock_supabase)
    user_id = uuid4()
    req_id = uuid4()
    existing_sid = uuid4()
    mock_supabase.execute_async.side_effect = [
        MagicMock(data=_req_row(req_id)),
        MagicMock(data=[{"id": str(existing_sid), "user_id": str(user_id), "status": "submitted"}]),
    ]
    await service.create_session(
        user_id=user_id, org_id=uuid4(), form_data=None,
        entry_point="complete_intake_btn", requisition_id=req_id,
    )

    _no_credit_charge.assert_not_awaited()
