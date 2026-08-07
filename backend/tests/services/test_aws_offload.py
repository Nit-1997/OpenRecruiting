"""BE-A1: blocking boto3/AWS calls reached from `async def` must be offloaded to a
threadpool (asyncio.to_thread) so they never block the event loop, and the boto3
clients must be cached at module scope (sync clients are thread-safe).

Also covers the CAS idempotency guard on FeedbackJobService.trigger_feedback_processing:
a second trigger for a round already in `processing` must NOT double-invoke the Lambda.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.feedback_job_service import FeedbackJobService
from app.services.jobs.invoker import LambdaInvoker


def _fluent_update_chain(execute_result):
    """Build a MagicMock that mimics the real fluent UpdateBuilder:
    supabase.table(...).update(...).eq(...).or_filter(...).execute_async()
    where every chained call returns the same builder and execute_async is awaitable.
    """
    builder = MagicMock()
    builder.update.return_value = builder
    builder.eq.return_value = builder
    builder.neq.return_value = builder
    builder.or_filter.return_value = builder
    builder.is_.return_value = builder
    builder.execute_async = AsyncMock(return_value=execute_result)
    supa = MagicMock()
    supa.table.return_value = builder
    return supa, builder


# ---------------------------------------------------------------------------
# FeedbackJobService — offload + CAS
# ---------------------------------------------------------------------------


async def test_lambda_invoker_offloads_boto3_invoke_to_thread():
    """The blocking boto3 invoke must be awaited via asyncio.to_thread, never
    called directly on the event loop."""
    client = MagicMock()
    client.invoke.return_value = {"StatusCode": 202}

    real_to_thread = asyncio.to_thread
    with patch("app.services.jobs.invoker.asyncio.to_thread", wraps=real_to_thread) as spy:
        await LambdaInvoker(client, {"feedback": "arn:feedback"}).invoke(
            "feedback", {"candidate_round_id": "cr-1"}
        )

    spy.assert_awaited_once()
    # to_thread was handed the sync invoke callable
    assert spy.call_args.args[0] == client.invoke


async def test_trigger_feedback_dispatches_via_invoker():
    """The service delegates transport to the JobInvoker seam so the same code
    path works against a local worker container or AWS Lambda."""
    service = FeedbackJobService()

    won = MagicMock(data=[{"id": "cr-1"}])  # claim won the row
    supa, _builder = _fluent_update_chain(won)
    invoker = MagicMock()
    invoker.invoke = AsyncMock()

    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=supa), \
         patch("app.services.feedback_job_service.get_invoker", return_value=invoker):
        result = await service.trigger_feedback_processing("cr-1", skip_prereq_check=True)

    assert result["status"] == "accepted"
    invoker.invoke.assert_awaited_once_with("feedback", {"candidate_round_id": "cr-1"})


async def test_trigger_feedback_claim_skips_when_already_processing():
    """If the claim RPC reports the row was already processing, the service must
    return the skipped contract and MUST NOT invoke the Lambda.

    The claim is made by the `claim_feedback_processing` RPC, which reports the
    winner via ROW_COUNT. (An in-Python CAS on the PATCH body cannot work here:
    PostgREST re-applies the request filter to the returned representation, so a
    SUCCESSFUL claim reads back empty and the round wedges in 'processing'.)

    This is the skip path, so it is exercised with skip_prereq_check=False.
    """
    service = FeedbackJobService()
    service.lambda_client = MagicMock()

    supa, _builder = _fluent_update_chain(MagicMock(data=[]))
    supa.rpc = AsyncMock(return_value=MagicMock(data=None))  # claim lost

    # Prereqs are a separate concern with their own tests; stub them so this
    # test isolates the claim/skip contract.
    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=supa), \
         patch.object(service, "can_process_feedback",
                      AsyncMock(return_value=(True, "Ready to process"))):
        result = await service.trigger_feedback_processing("cr-1", skip_prereq_check=False)

    assert result == {"status": "skipped", "reason": "already_processing", "candidate_round_id": "cr-1"}
    service.lambda_client.invoke.assert_not_called()


async def test_trigger_feedback_force_path_always_invokes():
    """skip_prereq_check=True is the documented force/override path: fresh
    transcript data must override an in-flight or wedged run, so it claims
    unconditionally and always (re)invokes. The Lambda's writes are idempotent
    on candidate_round_id, so a redundant invocation converges on the same state.
    This is what lets a force-reprocess recover a round stuck in 'processing'."""
    service = FeedbackJobService()

    supa, _builder = _fluent_update_chain(MagicMock(data=[]))
    invoker = MagicMock()
    invoker.invoke = AsyncMock()

    with patch("app.services.feedback_job_service.get_supabase_admin_client", return_value=supa), \
         patch("app.services.feedback_job_service.get_invoker", return_value=invoker):
        result = await service.trigger_feedback_processing("cr-1", skip_prereq_check=True)

    assert result["status"] == "accepted"
    invoker.invoke.assert_awaited_once()


@pytest.mark.parametrize("status_code", [200, 202, 204])
async def test_dispatch_accepts_any_2xx_from_worker(respx_mock, status_code):
    """Any 2xx from the worker counts as accepted, not only 202."""
    from app.services.jobs.invoker import HttpInvoker

    respx_mock.post("http://feedback-agent:9001/invoke").respond(status_code)

    # Does not raise -> accepted.
    await HttpInvoker({"feedback": "http://feedback-agent:9001"}).invoke(
        "feedback", {"candidate_round_id": "cr-1"}
    )


# ---------------------------------------------------------------------------
# s3_service — module-scope client cache
#
# NOTE: `upload_blog_image` stays synchronous because its only caller
# (admin/blog_posts.py:132) invokes it without `await` and that router file is
# OUT OF SCOPE for BE-A1. Offloading would require async-ifying the helper +
# editing the forbidden call site. We DO apply the module-scope client cache
# (the per-call boto3 client was the cheap, in-scope win). See BE-A1 report.
# ---------------------------------------------------------------------------


def test_get_s3_client_caches_across_calls():
    import app.services.s3_service as s3

    s3._s3_client = None
    settings = MagicMock()
    settings.AWS_REGION = "us-west-1"
    settings.AWS_ACCESS_KEY_ID = "k"
    settings.AWS_SECRET_ACCESS_KEY = "s"
    try:
        with patch.object(s3, "boto3") as mock_boto, \
             patch.object(s3, "get_settings", return_value=settings):
            mock_boto.client.return_value = MagicMock()
            first = s3.get_s3_client()
            second = s3.get_s3_client()
        assert first is second
        mock_boto.client.assert_called_once()
    finally:
        s3._s3_client = None


def test_upload_blog_image_rejects_non_image():
    import app.services.s3_service as s3

    with pytest.raises(ValueError):
        s3.upload_blog_image(b"x", "f.txt", "text/plain")


# ---------------------------------------------------------------------------
# intake_job_service — offload
# ---------------------------------------------------------------------------


async def test_intake_trigger_dispatches_via_invoker():
    """Offloading boto3 to a thread is now LambdaInvoker's job (covered by
    test_lambda_invoker_offloads_boto3_invoke_to_thread); the intake service's
    responsibility is simply to dispatch through the seam."""
    from app.services.intake_job_service import IntakeJobService

    service = IntakeJobService()
    invoker = MagicMock()
    invoker.invoke = AsyncMock()
    supa = MagicMock()

    with patch("app.services.intake_job_service.get_invoker", return_value=invoker):
        result = await service._trigger_via_lambda("req-1", supa)

    assert result["status"] == "accepted"
    invoker.invoke.assert_awaited_once_with("intake_transcript", {"requisition_id": "req-1"})
