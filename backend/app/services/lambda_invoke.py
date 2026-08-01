"""Generic AWS Lambda async invocation helper for v2 services."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import boto3
import structlog

logger = structlog.get_logger(__name__)

# Module-scope boto3 lambda client (sync, thread-safe). Previously a fresh
# client was constructed on every call — wasteful. A process-wide singleton is
# correct (NOT a loop-bound async resource, so the CLAUDE.md async-resource
# caching rule does not apply). BE-A1.
_lambda_client = None


def _get_lambda_client():
    global _lambda_client
    if _lambda_client is None:
        region = os.getenv("AWS_REGION", "us-west-1")
        _lambda_client = boto3.client("lambda", region_name=region)
    return _lambda_client


def _invoke_blocking(function_arn: str, payload: dict[str, Any]) -> None:
    """Synchronous boto3 invoke — runs on a worker thread, never the event loop."""
    client = _get_lambda_client()

    response = client.invoke(
        FunctionName=function_arn,
        InvocationType="Event",
        Payload=json.dumps(payload),
    )

    if response.get("StatusCode") not in (200, 202):
        logger.error(
            "lambda_invoke_unexpected_status",
            function_arn=function_arn,
            status_code=response.get("StatusCode"),
        )
        raise RuntimeError(f"Lambda invoke returned status {response.get('StatusCode')}")

    logger.info("lambda_invoked", function_arn=function_arn)


async def invoke_lambda_async(function_arn: str, payload: dict[str, Any]) -> None:
    """Invoke a Lambda function asynchronously (InvocationType='Event').

    BE-A2: the boto3 invoke is blocking I/O, so it runs in a worker thread via
    ``asyncio.to_thread`` to avoid stalling the FastAPI event loop. boto3 exceptions
    propagate to the caller for explicit handling (status rollback). The boto3
    lambda client is module-cached (BE-A1) — it is a plain sync client, NOT a
    loop-bound async resource, so the CLAUDE.md async-resource caching rule does
    not apply to it.
    """
    await asyncio.to_thread(_invoke_blocking, function_arn, payload)
