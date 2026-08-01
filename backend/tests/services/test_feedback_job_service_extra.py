"""Characterization tests for the uncovered FeedbackJobService paths:
can_process_feedback prereq gate, get_processing_status, and the dispatch
failure branches that flip the round to `failed`.

Dispatch goes through the JobInvoker seam (services/jobs/invoker.py), so these
patch `get_invoker` rather than a boto3 client: the service is transport-
agnostic and a failure surfaces as a raised exception either way.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.services.feedback_job_service import (
    FeedbackJobService,
    FeedbackJobServiceError,
)


def _ok_invoker():
    """An invoker whose dispatch succeeds."""
    invoker = MagicMock()
    invoker.invoke = AsyncMock()
    return invoker


def _failing_invoker(exc):
    """An invoker whose dispatch fails with `exc`."""
    invoker = MagicMock()
    invoker.invoke = AsyncMock(side_effect=exc)
    return invoker


def _supabase_by_table(table_results, rpc_result=None):
    """Return a supabase mock where table(name) -> builder whose execute_async
    yields the configured result (a MagicMock with .data). Update chains reuse
    the same per-table builder, so update+select both resolve from the map.

    `rpc_result` (a MagicMock with .data) backs sb.rpc(...) for the atomic
    claim_feedback_processing CAS used by the non-force trigger path.
    """
    sb = MagicMock()

    def table(name):
        builder = MagicMock()
        for attr in ("select", "update", "eq", "neq", "is_null", "in_", "or_filter"):
            setattr(builder, attr, MagicMock(return_value=builder))
        builder.execute_async = AsyncMock(return_value=table_results[name])
        return builder

    sb.table = MagicMock(side_effect=table)
    sb.rpc = AsyncMock(return_value=rpc_result if rpc_result is not None else _res(False))
    return sb


def _res(data):
    return MagicMock(data=data)


# ----------------------- can_process_feedback -----------------------

@pytest.mark.asyncio
async def test_can_process_round_not_found():
    sb = _supabase_by_table({"candidate_rounds": _res([])})
    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=sb):
        ok, reason = await FeedbackJobService().can_process_feedback("cr1")
    assert ok is False and "not found" in reason


@pytest.mark.asyncio
async def test_can_process_already_processing():
    sb = _supabase_by_table({"candidate_rounds": _res([{"id": "cr1", "round_id": "r1", "processing_status": "processing"}])})
    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=sb):
        ok, reason = await FeedbackJobService().can_process_feedback("cr1")
    assert ok is False and reason == "Already processing"


@pytest.mark.asyncio
async def test_can_process_no_transcript():
    sb = _supabase_by_table({
        "candidate_rounds": _res([{"id": "cr1", "round_id": "r1", "processing_status": "pending"}]),
        "transcripts": _res([]),
    })
    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=sb):
        ok, reason = await FeedbackJobService().can_process_feedback("cr1")
    assert ok is False and reason == "No transcript found"


@pytest.mark.asyncio
async def test_can_process_empty_segments():
    sb = _supabase_by_table({
        "candidate_rounds": _res([{"id": "cr1", "round_id": "r1", "processing_status": "pending"}]),
        "transcripts": _res([{"id": "t1", "segments": []}]),
    })
    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=sb):
        ok, reason = await FeedbackJobService().can_process_feedback("cr1")
    assert ok is False and reason == "No transcript segments found"


@pytest.mark.asyncio
async def test_can_process_no_questions():
    sb = _supabase_by_table({
        "candidate_rounds": _res([{"id": "cr1", "round_id": "r1", "processing_status": "pending"}]),
        "transcripts": _res([{"id": "t1", "segments": [{"text": "hi"}]}]),
        "feedback_questions": _res([]),
    })
    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=sb):
        ok, reason = await FeedbackJobService().can_process_feedback("cr1")
    assert ok is False and reason == "No scorecard questions configured"


@pytest.mark.asyncio
async def test_can_process_ready():
    sb = _supabase_by_table({
        "candidate_rounds": _res([{"id": "cr1", "round_id": "r1", "processing_status": "pending"}]),
        "transcripts": _res([{"id": "t1", "segments": [{"text": "hi"}]}]),
        "feedback_questions": _res([{"id": "q1"}]),
    })
    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=sb):
        ok, reason = await FeedbackJobService().can_process_feedback("cr1")
    assert ok is True and reason == "Ready to process"


# ----------------------- trigger prereq rejection -----------------------

@pytest.mark.asyncio
async def test_trigger_rejects_when_prereq_fails():
    sb = _supabase_by_table({"candidate_rounds": _res([])})
    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=sb):
        result = await FeedbackJobService().trigger_feedback_processing("cr1")
    assert result["status"] == "rejected"
    assert "not found" in result["reason"]


# ----------------------- atomic claim (CAS) -----------------------


@pytest.mark.asyncio
async def test_trigger_claims_via_rpc_then_invokes():
    """Non-force path claims through the claim_feedback_processing RPC; a won
    claim (rpc -> True) proceeds to invoke the Lambda. Regression for the
    PostgREST return=representation re-filter that read a successful claim back
    as empty and silently skipped the Lambda."""
    sb = _supabase_by_table(
        {
            "candidate_rounds": _res([{"id": "cr1", "round_id": "r1", "processing_status": "none"}]),
            "transcripts": _res([{"id": "t1", "segments": [{"text": "hi"}]}]),
            "feedback_questions": _res([{"id": "q1"}]),
        },
        rpc_result=_res(True),
    )
    service = FeedbackJobService()
    invoker = _ok_invoker()
    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=sb), \
         patch("app.services.feedback_job_service.get_invoker", return_value=invoker):
        result = await service.trigger_feedback_processing("cr1")
    sb.rpc.assert_awaited_once_with("claim_feedback_processing", {"p_cr_id": "cr1"})
    invoker.invoke.assert_awaited_once()
    assert result["status"] == "accepted"


@pytest.mark.asyncio
async def test_trigger_skips_when_claim_lost():
    """Non-force path: a lost claim (rpc -> False) skips without invoking — the
    real concurrency guard against double-invocation."""
    sb = _supabase_by_table(
        {
            "candidate_rounds": _res([{"id": "cr1", "round_id": "r1", "processing_status": "none"}]),
            "transcripts": _res([{"id": "t1", "segments": [{"text": "hi"}]}]),
            "feedback_questions": _res([{"id": "q1"}]),
        },
        rpc_result=_res(False),
    )
    service = FeedbackJobService()
    service.lambda_client = MagicMock()
    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=sb):
        result = await service.trigger_feedback_processing("cr1")
    assert result["status"] == "skipped"
    assert result["reason"] == "already_processing"
    service.lambda_client.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_force_bypasses_claim_and_invokes():
    """skip_prereq_check=True is the force/override path: it claims
    unconditionally (no claim RPC) and always invokes, so a round wedged in
    'processing' can be recovered and fresh data overrides an in-flight run."""
    sb = _supabase_by_table(
        {"candidate_rounds": _res([{"id": "cr1"}])},
        rpc_result=_res(False),  # would skip if the force path consulted it
    )
    service = FeedbackJobService()
    invoker = _ok_invoker()
    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=sb), \
         patch("app.services.feedback_job_service.get_invoker", return_value=invoker):
        result = await service.trigger_feedback_processing("cr1", skip_prereq_check=True)
    sb.rpc.assert_not_awaited()
    invoker.invoke.assert_awaited_once()
    assert result["status"] == "accepted"


# ----------------------- trigger lambda non-2xx / errors -----------------------

@pytest.mark.asyncio
async def test_trigger_worker_dispatch_failure_marks_failed_and_raises():
    """A worker that rejects the dispatch (e.g. HTTP 500) must flip the round to
    `failed` and surface the error rather than reporting success."""
    import httpx

    won = _res([{"id": "cr1"}])
    sb = _supabase_by_table({"candidate_rounds": won})
    service = FeedbackJobService()
    boom = httpx.HTTPStatusError(
        "500 Server Error",
        request=httpx.Request("POST", "http://feedback-agent:9001/invoke"),
        response=httpx.Response(500),
    )
    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=sb), \
         patch("app.services.feedback_job_service.get_invoker", return_value=_failing_invoker(boom)):
        with pytest.raises(FeedbackJobServiceError) as exc:
            await service.trigger_feedback_processing("cr1", skip_prereq_check=True)
    assert exc.value.error_code == "UNEXPECTED_ERROR"


@pytest.mark.asyncio
async def test_trigger_lambda_client_error_raises():
    """The AWS transport's ClientError keeps its dedicated branch so the AWS
    error code is preserved on the raised FeedbackJobServiceError."""
    won = _res([{"id": "cr1"}])
    sb = _supabase_by_table({"candidate_rounds": won})
    service = FeedbackJobService()
    boom = ClientError(
        {"Error": {"Code": "Throttling", "Message": "rate limited"}}, "Invoke"
    )
    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=sb), \
         patch("app.services.feedback_job_service.get_invoker", return_value=_failing_invoker(boom)):
        with pytest.raises(FeedbackJobServiceError) as exc:
            await service.trigger_feedback_processing("cr1", skip_prereq_check=True)
    assert exc.value.error_code == "Throttling"


@pytest.mark.asyncio
async def test_trigger_unexpected_error_raises():
    won = _res([{"id": "cr1"}])
    sb = _supabase_by_table({"candidate_rounds": won})
    service = FeedbackJobService()
    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=sb), \
         patch("app.services.feedback_job_service.get_invoker",
               return_value=_failing_invoker(RuntimeError("kaboom"))):
        with pytest.raises(FeedbackJobServiceError) as exc:
            await service.trigger_feedback_processing("cr1", skip_prereq_check=True)
    assert exc.value.error_code == "UNEXPECTED_ERROR"


# ----------------------- get_processing_status -----------------------

@pytest.mark.asyncio
async def test_get_processing_status_found():
    row = {
        "id": "cr1", "processing_status": "completed", "processing_error": None,
        "processing_started_at": "t0", "processing_completed_at": "t1",
        "rating": 4, "summary": "good",
    }
    sb = _supabase_by_table({"candidate_rounds": _res([row])})
    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=sb):
        result = await FeedbackJobService().get_processing_status("cr1")
    assert result["found"] is True
    assert result["processing_status"] == "completed"
    assert result["rating"] == 4


@pytest.mark.asyncio
async def test_get_processing_status_not_found():
    sb = _supabase_by_table({"candidate_rounds": _res([])})
    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=sb):
        result = await FeedbackJobService().get_processing_status("cr1")
    assert result == {"found": False, "candidate_round_id": "cr1"}
