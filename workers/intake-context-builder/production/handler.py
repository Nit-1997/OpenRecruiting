"""AWS Lambda handler entry point for intake-agent-context-builder."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import structlog

# Ensure src/ is on path
sys.path.insert(0, "/var/task/src")

logger = structlog.get_logger(__name__)


def handler(event: dict[str, Any], context) -> dict[str, Any]:
    session_id = event.get("session_id")
    include_turns = event.get("include_turns", False)
    if not session_id:
        return {"statusCode": 400, "body": "missing session_id"}

    logger.info("invoked", session_id=session_id, include_turns=include_turns)

    # Per CLAUDE.md "Lambda Code — Mandatory Rules", create a fresh event loop
    # for each invocation and close async resources in the entry coroutine's finally.
    loop = asyncio.new_event_loop()
    try:
        from src.pipeline import run_pipeline  # noqa: E402
        result = loop.run_until_complete(run_pipeline(session_id=session_id, include_turns=include_turns))
    finally:
        loop.close()

    return {"statusCode": 200, "body": json.dumps(result)}
