"""Where background jobs actually run.

The feedback and intake workers began life as AWS Lambdas. A self-hosted
instance has no AWS, so the same handlers also ship as small containers with a
`POST /invoke` endpoint. This module is the seam between the two, chosen by the
`JOB_INVOKER` setting:

    JOB_INVOKER=http    -> HttpInvoker,   posts to the worker containers
    JOB_INVOKER=lambda  -> LambdaInvoker, the original boto3 path

Both are fire-and-forget from the caller's point of view: the worker owns the
job's terminal state and writes it back to the database. What the caller does
need is to hear about a *dispatch* failure, so both raise on one.
"""

from __future__ import annotations

import asyncio
import json
from typing import Protocol

import httpx

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

# Logical job names. Callers use these, not URLs or ARNs.
#
# INTAKE and INTAKE_TRANSCRIPT are two DIFFERENT jobs with different payloads --
# do not merge them:
#   INTAKE             -> workers/intake-agent, payload {"session_id": ...}
#                         the recruiter's self-serve intake session.
#   CONTEXT_BUILDER    -> workers/intake-context-builder,
#                         payload {"session_id": ..., "include_turns": bool}
#                         prefill and reprocess for an intake session.
#   INTAKE_TRANSCRIPT  -> payload {"requisition_id": ...}
#                         the older staff-only tool that processes a pasted
#                         transcript. Its worker is not part of this repo, so it
#                         has no default URL: in http mode it raises rather than
#                         posting a requisition_id to a worker that wants a
#                         session_id and silently 400s.
FEEDBACK = "feedback"
INTAKE = "intake"
CONTEXT_BUILDER = "context_builder"
INTAKE_TRANSCRIPT = "intake_transcript"

# Ceiling on a single dispatch, not on the job. The POST is awaited on a
# background task purely so a failure gets logged, so this only bounds how long
# a stuck socket is held: it must exceed the slowest worker (feedback runs ~50s
# against the LLM) or the log line will claim a failure that did not happen.
_HTTP_TIMEOUT_SECONDS = 600.0

# create_task keeps only a weak reference, so a dispatch still in flight can be
# garbage-collected mid-request. Hold a strong reference until it finishes.
_IN_FLIGHT: set[asyncio.Task] = set()


class UnknownJobTargetError(ValueError):
    """Raised when a caller asks for a job target that is not configured."""


class JobInvoker(Protocol):
    async def invoke(self, target: str, payload: dict) -> None: ...


class HttpInvoker:
    """Posts the Lambda-shaped payload to a worker container.

    The workers accept exactly the event dict the Lambda handler expects, so
    the payload is identical on both transports.

    The worker's `POST /invoke` is a synchronous handler: it answers only once
    the whole job is done, which for the LLM pipelines is 30-50s. Awaiting that
    would make every dispatch look like a failure to the caller, so the POST
    goes onto a background task and `invoke` returns as soon as it is queued --
    matching `LambdaInvoker`'s InvocationType="Event" and the fire-and-forget
    contract in this module's docstring. The worker owns the job's terminal
    state either way, so nothing is lost by not waiting.

    Consequence worth knowing: only *configuration* failures (an unroutable
    target) still raise. A worker that is merely unreachable now surfaces as an
    error in the log rather than an exception at the call site, and the job's
    row keeps whatever pending state the caller wrote before dispatching.
    """

    def __init__(self, routes: dict[str, str]):
        self._routes = routes

    async def invoke(self, target: str, payload: dict) -> None:
        base = self._routes.get(target)
        if not base:
            raise UnknownJobTargetError(
                f"No worker URL configured for job target {target!r}. "
                f"Set the matching *_WORKER_URL environment variable."
            )
        url = f"{base.rstrip('/')}/invoke"
        task = asyncio.create_task(self._deliver(url, target, payload))
        _IN_FLIGHT.add(task)
        task.add_done_callback(_IN_FLIGHT.discard)
        logger.info("job_dispatched", extra={"target": target, "transport": "http"})

    @staticmethod
    async def _deliver(url: str, target: str, payload: dict) -> None:
        """Run the POST to completion so the outcome is logged. Never raises:
        this runs detached, and an escaping exception would only be reported by
        asyncio as a task that was never retrieved."""
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except Exception as e:
            logger.error(
                "job_delivery_failed",
                extra={"target": target, "transport": "http", "error": str(e)},
            )
        else:
            logger.info("job_completed", extra={"target": target, "transport": "http"})


class LambdaInvoker:
    """The original AWS path, for anyone deploying to Lambda."""

    def __init__(self, client, arns: dict[str, str]):
        self._client = client
        self._arns = arns

    async def invoke(self, target: str, payload: dict) -> None:
        arn = self._arns.get(target)
        if not arn:
            raise UnknownJobTargetError(
                f"No Lambda ARN configured for job target {target!r}."
            )
        # boto3 is synchronous; keep the blocking call off the event loop.
        await asyncio.to_thread(
            self._client.invoke,
            FunctionName=arn,
            InvocationType="Event",
            Payload=json.dumps(payload).encode(),
        )
        logger.info("job_dispatched", extra={"target": target, "transport": "lambda"})


def _boto3_lambda_client(region: str):
    # Imported lazily so an http-only deployment never needs botocore loaded.
    import boto3

    return boto3.client("lambda", region_name=region)


def get_invoker() -> JobInvoker:
    settings = get_settings()
    if (settings.JOB_INVOKER or "").strip().lower() == "lambda":
        return LambdaInvoker(
            _boto3_lambda_client(settings.AWS_REGION),
            {
                FEEDBACK: settings.FEEDBACK_LAMBDA_ARN,
                INTAKE: settings.INTAKE_LAMBDA_ARN_V2 or "",
                CONTEXT_BUILDER: settings.INTAKE_CONTEXT_BUILDER_LAMBDA_ARN,
                INTAKE_TRANSCRIPT: settings.INTAKE_LAMBDA_ARN,
            },
        )
    return HttpInvoker(
        {
            FEEDBACK: settings.FEEDBACK_WORKER_URL,
            INTAKE: settings.INTAKE_WORKER_URL,
            CONTEXT_BUILDER: settings.CONTEXT_BUILDER_WORKER_URL,
            # Intentionally blank by default -- see the INTAKE_TRANSCRIPT note above.
            INTAKE_TRANSCRIPT: settings.INTAKE_TRANSCRIPT_WORKER_URL,
        }
    )
