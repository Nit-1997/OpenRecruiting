"""HTTP wrapper so the intake-agent worker can run as a container instead of a Lambda.

The Lambda handler is used verbatim -- this only changes how it is triggered.
`POST /invoke` takes the same event dict the Lambda received, so the two
transports stay byte-identical and nothing about the job logic forks.

Two details matter:

1. The handler is synchronous and builds its own event loop, so it is run via
   asyncio.to_thread rather than on the server's loop.
2. AWS runs at most one invocation per container at a time, and the handler
   relies on that: it caches loop-bound async clients in module globals and
   tears them down in a finally block. Serving concurrent requests in one
   process would let two invocations share and close each other's clients, so
   invocations are serialised here to keep the Lambda's guarantee.
"""

import asyncio

from fastapi import FastAPI, Request

from production.handler import handler

app = FastAPI(title="intake-agent worker")

# Preserves the Lambda "one invocation per container" guarantee (see above).
_invoke_lock = asyncio.Semaphore(1)


class _Context:
    """The subset of the Lambda context object the handler actually reads."""

    function_name = "intake-agent"
    aws_request_id = "local"


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "worker": "intake-agent"}


@app.post("/invoke")
async def invoke(request: Request) -> dict:
    event = await request.json()
    async with _invoke_lock:
        return await asyncio.to_thread(handler, event, _Context())
