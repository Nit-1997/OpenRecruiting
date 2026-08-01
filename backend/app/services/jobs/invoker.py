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

_HTTP_TIMEOUT_SECONDS = 15.0


class UnknownJobTargetError(ValueError):
    """Raised when a caller asks for a job target that is not configured."""


class JobInvoker(Protocol):
    async def invoke(self, target: str, payload: dict) -> None: ...


class HttpInvoker:
    """Posts the Lambda-shaped payload to a worker container.

    The workers accept exactly the event dict the Lambda handler expects, so
    the payload is identical on both transports.
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
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        logger.info("job_dispatched", extra={"target": target, "transport": "http"})


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
