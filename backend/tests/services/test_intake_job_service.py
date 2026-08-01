"""Behavioral tests for IntakeJobService — the can-process gate, the claim-lock
trigger flow, Lambda invoke success/non-2xx/ClientError handling, and the
status read.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.services.intake_job_service import IntakeJobService, IntakeJobServiceError


def _builder(execute_result):
    b = MagicMock()
    for m in ("table", "select", "update", "eq", "is_null"):
        getattr(b, m).return_value = b
    b.execute_async = AsyncMock(return_value=execute_result)
    return b


def _supa(execute_result):
    b = _builder(execute_result)
    supa = MagicMock()
    supa.table.return_value = b
    return supa, b


def _resp(data):
    return MagicMock(data=data)


def _svc():
    svc = IntakeJobService()
    svc.function_arn = "arn:aws:lambda:us-west-1:111:function:intake"
    return svc


# ---------------------------------------------------------------------------
# can_process_intake
# ---------------------------------------------------------------------------


async def test_can_process_not_found():
    svc = _svc()
    supa, _ = _supa(_resp([]))
    with patch("app.services.intake_job_service.get_supabase_admin_client", return_value=supa):
        ok, reason = await svc.can_process_intake("req-x")
    assert ok is False and reason == "Requisition not found"


async def test_can_process_already_processing_recent():
    svc = _svc()
    started = datetime.now(timezone.utc).isoformat()
    supa, _ = _supa(_resp([{
        "id": "req-1",
        "intake_processing_status": "processing",
        "intake_processing_started_at": started,
        "intake_transcript": "t",
    }]))
    with patch("app.services.intake_job_service.get_supabase_admin_client", return_value=supa):
        ok, reason = await svc.can_process_intake("req-1")
    assert ok is False and reason == "Already processing"


async def test_can_process_stale_processing_allows_retry():
    svc = _svc()
    started = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
    supa, _ = _supa(_resp([{
        "id": "req-1",
        "intake_processing_status": "processing",
        "intake_processing_started_at": started,
        "intake_transcript": "t",
    }]))
    with patch("app.services.intake_job_service.get_supabase_admin_client", return_value=supa):
        ok, reason = await svc.can_process_intake("req-1")
    assert ok is True


async def test_can_process_no_transcript():
    svc = _svc()
    supa, _ = _supa(_resp([{
        "id": "req-1",
        "intake_processing_status": "pending",
        "intake_transcript": None,
    }]))
    with patch("app.services.intake_job_service.get_supabase_admin_client", return_value=supa):
        ok, reason = await svc.can_process_intake("req-1")
    assert ok is False and reason == "No intake transcript found"


async def test_can_process_ready():
    svc = _svc()
    supa, _ = _supa(_resp([{
        "id": "req-1",
        "intake_processing_status": "pending",
        "intake_transcript": "real transcript",
    }]))
    with patch("app.services.intake_job_service.get_supabase_admin_client", return_value=supa):
        ok, reason = await svc.can_process_intake("req-1")
    assert ok is True and reason == "Ready to process"


# ---------------------------------------------------------------------------
# trigger_intake_processing — claim lock
# ---------------------------------------------------------------------------


async def test_trigger_rejected_when_claim_lost():
    svc = _svc()
    supa = MagicMock()
    supa.rpc = AsyncMock(return_value=_resp(None))  # claim returned nothing
    with patch("app.services.intake_job_service.get_supabase_admin_client", return_value=supa):
        result = await svc.trigger_intake_processing("req-1")
    assert result["status"] == "rejected"
    assert result["reason"] == "Already processing"


def _ok_invoker():
    invoker = MagicMock()
    invoker.invoke = AsyncMock()
    return invoker


def _failing_invoker(exc):
    invoker = MagicMock()
    invoker.invoke = AsyncMock(side_effect=exc)
    return invoker


async def test_trigger_accepts_after_claim():
    svc = _svc()
    invoker = _ok_invoker()

    supa = MagicMock()
    supa.rpc = AsyncMock(return_value=_resp(True))  # claim won
    with patch("app.services.intake_job_service.get_supabase_admin_client", return_value=supa), \
         patch("app.services.intake_job_service.get_invoker", return_value=invoker):
        result = await svc.trigger_intake_processing("req-1")
    assert result["status"] == "accepted"
    invoker.invoke.assert_awaited_once_with("intake_transcript", {"requisition_id": "req-1"})


# ---------------------------------------------------------------------------
# dispatch failure branches
# ---------------------------------------------------------------------------


async def test_trigger_worker_dispatch_failure_marks_failed_and_raises():
    """A worker that rejects the dispatch must persist `failed` on the
    requisition and surface the error, never report success."""
    import httpx

    svc = _svc()
    boom = httpx.HTTPStatusError(
        "500 Server Error",
        request=httpx.Request("POST", "http://intake-agent:9002/invoke"),
        response=httpx.Response(500),
    )
    supa, builder = _supa(_resp([]))
    with patch("app.services.intake_job_service.get_invoker", return_value=_failing_invoker(boom)):
        with pytest.raises(IntakeJobServiceError) as e:
            await svc._trigger_via_lambda("req-1", supa)
    assert e.value.error_code == "UNEXPECTED_ERROR"
    # The failure was persisted to the requisition row.
    builder.update.assert_called()


async def test_trigger_via_lambda_client_error_raises_service_error():
    svc = _svc()
    boom = ClientError(
        {"Error": {"Code": "Throttling", "Message": "slow down"}}, "Invoke"
    )
    supa, builder = _supa(_resp([]))
    with patch("app.services.intake_job_service.get_invoker", return_value=_failing_invoker(boom)):
        with pytest.raises(IntakeJobServiceError) as e:
            await svc._trigger_via_lambda("req-1", supa)
    assert e.value.error_code == "Throttling"
    builder.update.assert_called()


async def test_trigger_via_lambda_unexpected_error_raises():
    svc = _svc()
    supa, builder = _supa(_resp([]))
    with patch("app.services.intake_job_service.get_invoker",
               return_value=_failing_invoker(RuntimeError("boom"))):
        with pytest.raises(IntakeJobServiceError) as e:
            await svc._trigger_via_lambda("req-1", supa)
    assert e.value.error_code == "UNEXPECTED_ERROR"


# ---------------------------------------------------------------------------
# get_processing_status
# ---------------------------------------------------------------------------


async def test_get_processing_status_not_found():
    svc = _svc()
    supa, _ = _supa(_resp([]))
    with patch("app.services.intake_job_service.get_supabase_admin_client", return_value=supa):
        result = await svc.get_processing_status("req-x")
    assert result["found"] is False


async def test_get_processing_status_found():
    svc = _svc()
    supa, _ = _supa(_resp([{
        "id": "req-1",
        "intake_processing_status": "completed",
        "intake_processing_error": None,
        "intake_processing_started_at": "t0",
        "intake_processing_completed_at": "t1",
        "intake_processing_stage": "done",
        "intake_summary": "summary",
    }]))
    with patch("app.services.intake_job_service.get_supabase_admin_client", return_value=supa):
        result = await svc.get_processing_status("req-1")
    assert result["found"] is True
    assert result["intake_processing_status"] == "completed"
    assert result["intake_summary"] == "summary"
