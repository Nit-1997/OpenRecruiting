"""Tests for the JobInvoker seam.

The backend used to call boto3 Lambda directly. Self-hosters do not have AWS,
so the workers run as local containers instead and the invoker chooses the
transport: `http` posts to a container, `lambda` keeps the original boto3 path.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.jobs.invoker import (
    _IN_FLIGHT,
    HttpInvoker,
    LambdaInvoker,
    UnknownJobTargetError,
    get_invoker,
)


async def _drain() -> None:
    """Wait for dispatches HttpInvoker left running in the background.

    `invoke` returns as soon as the POST is queued, so a test that asserts on
    the request has to wait for it; production code never needs this.
    """
    while _IN_FLIGHT:
        await asyncio.gather(*list(_IN_FLIGHT), return_exceptions=True)


def _settings(**kw):
    base = {
        "JOB_INVOKER": "http",
        "FEEDBACK_WORKER_URL": "http://feedback-agent:9001",
        "INTAKE_WORKER_URL": "http://intake-agent:9002",
        "CONTEXT_BUILDER_WORKER_URL": "http://intake-context-builder:9003",
        "INTAKE_TRANSCRIPT_WORKER_URL": "",
        "AWS_REGION": "us-west-1",
        "FEEDBACK_LAMBDA_ARN": "arn:aws:lambda:us-west-1:1:function:feedback",
        "INTAKE_LAMBDA_ARN_V2": "arn:aws:lambda:us-west-1:1:function:intake",
        "INTAKE_LAMBDA_ARN": "arn:aws:lambda:us-west-1:1:function:intake-transcript",
        "INTAKE_CONTEXT_BUILDER_LAMBDA_ARN": "arn:aws:lambda:us-west-1:1:function:ctx",
    }
    base.update(kw)
    return SimpleNamespace(**base)


# --------------------------- HttpInvoker ---------------------------


async def test_http_invoker_posts_payload_to_worker(respx_mock):
    route = respx_mock.post("http://feedback-agent:9001/invoke").respond(200)

    await HttpInvoker({"feedback": "http://feedback-agent:9001"}).invoke(
        "feedback", {"candidate_round_id": "cr-1"}
    )
    await _drain()

    assert route.called
    assert route.calls[0].request.content == b'{"candidate_round_id": "cr-1"}'


async def test_http_invoker_strips_trailing_slash_on_base_url(respx_mock):
    """A trailing slash in the env value must not produce a //invoke path."""
    route = respx_mock.post("http://feedback-agent:9001/invoke").respond(200)

    await HttpInvoker({"feedback": "http://feedback-agent:9001/"}).invoke(
        "feedback", {"candidate_round_id": "cr-1"}
    )
    await _drain()

    assert route.called


async def test_http_invoker_rejects_unknown_target():
    with pytest.raises(UnknownJobTargetError):
        await HttpInvoker({}).invoke("nope", {})


async def test_http_invoker_returns_before_the_worker_finishes(respx_mock):
    """The regression this guards.

    `POST /invoke` is a synchronous handler that answers only once the job is
    done -- 30-50s for the LLM pipelines. Awaiting it made every dispatch time
    out and report a failure for work that then succeeded, so `invoke` must
    return while the worker is still going.
    """
    finish = asyncio.Event()

    async def still_working(request):
        await finish.wait()
        return httpx.Response(200)

    respx_mock.post("http://feedback-agent:9001/invoke").mock(side_effect=still_working)

    await asyncio.wait_for(
        HttpInvoker({"feedback": "http://feedback-agent:9001"}).invoke(
            "feedback", {"candidate_round_id": "cr-1"}
        ),
        timeout=1.0,
    )

    finish.set()
    await _drain()


async def test_http_invoker_does_not_raise_when_the_worker_errors(respx_mock):
    """Only dispatch failures reach the caller. The worker owns the job's
    terminal state, so it reports its own failure to the database -- raising
    here would make the caller overwrite that with a second, wrong verdict."""
    respx_mock.post("http://feedback-agent:9001/invoke").respond(500)

    await HttpInvoker({"feedback": "http://feedback-agent:9001"}).invoke(
        "feedback", {"candidate_round_id": "cr-1"}
    )
    await _drain()


# --------------------------- LambdaInvoker ---------------------------


async def test_lambda_invoker_calls_boto3_off_the_event_loop():
    client = MagicMock()
    client.invoke.return_value = {"StatusCode": 202}

    await LambdaInvoker(client, {"feedback": "arn:feedback"}).invoke(
        "feedback", {"candidate_round_id": "cr-1"}
    )

    client.invoke.assert_called_once()
    kwargs = client.invoke.call_args.kwargs
    assert kwargs["FunctionName"] == "arn:feedback"
    assert kwargs["InvocationType"] == "Event"
    assert b"cr-1" in kwargs["Payload"]


# --------------------------- selection ---------------------------


def test_get_invoker_returns_http_when_configured():
    with patch("app.services.jobs.invoker.get_settings", lambda: _settings(JOB_INVOKER="http")):
        assert isinstance(get_invoker(), HttpInvoker)


def test_get_invoker_returns_lambda_when_configured():
    with patch("app.services.jobs.invoker.get_settings", lambda: _settings(JOB_INVOKER="lambda")), \
         patch("app.services.jobs.invoker._boto3_lambda_client", lambda region: MagicMock()):
        assert isinstance(get_invoker(), LambdaInvoker)


def test_get_invoker_is_case_insensitive():
    with patch("app.services.jobs.invoker.get_settings", lambda: _settings(JOB_INVOKER="HTTP")):
        assert isinstance(get_invoker(), HttpInvoker)
