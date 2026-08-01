"""Shared async building blocks for the intake submit / reprocess / publish lifecycle.

BE-A2: submit, reprocess and publish each independently re-implemented the same
three-step shape:

  1. load the caller-owned session row (scoped to user_id + organization_id);
  2. optimistically flip a status column with a race-gate predicate (Postgres
     serializes the row lock so only ONE concurrent writer matches → the others
     see zero rows and surface a 409);
  3. invoke the worker Lambda and, on invoke failure, roll the status back so the
     user can retry.

These helpers own ONLY that mechanical shape. They deliberately carry NO business
rules — which statuses are submittable, which run-id to bump, what the rollback
payload contains, and the 404/409 mapping all stay in the calling service.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog

from app.services._supabase_rows import first_row
from app.services.jobs.invoker import get_invoker

logger = structlog.get_logger(__name__)

# (filter_method_name, column, value) — applied to a builder via getattr.
GuardFilter = tuple[str, str, Any]


async def load_owned_session(
    supabase,
    *,
    session_id: UUID,
    user_id: UUID,
    organization_id: UUID,
    columns: str,
) -> Optional[dict]:
    """Load a single intake_sessions row scoped to the caller, or None.

    Returns the row dict on a hit and None when the (id, user_id, organization_id)
    filter matches nothing. Callers decide what "None" means (typically a 404) —
    this helper never raises on the empty case.
    """
    resp = await (
        supabase.table("intake_sessions")
        .select(columns)
        .eq("id", str(session_id))
        .eq("user_id", str(user_id))
        .eq("organization_id", str(organization_id))
        .single()
        .execute_async()
    )
    return first_row(resp)


async def optimistic_flip(
    supabase,
    *,
    session_id: UUID,
    user_id: UUID,
    organization_id: UUID,
    values: dict[str, Any],
    guards: list[GuardFilter],
) -> bool:
    """Conditionally UPDATE the session and report whether a row matched.

    ``guards`` are extra predicates applied on top of the (id, user_id,
    organization_id) scope — e.g. ``[("in_", "status", ["ready", "active"])]`` or
    ``[("eq", "process_status", "idle")]``. They are the race gate: when a
    concurrent request already transitioned the row, this returns ``False`` and the
    caller raises 409 instead of double-invoking the Lambda.
    """
    builder = (
        supabase.table("intake_sessions")
        .update(values)
        .eq("id", str(session_id))
        .eq("user_id", str(user_id))
        .eq("organization_id", str(organization_id))
    )
    for method, column, value in guards:
        builder = getattr(builder, method)(column, value)
    resp = await builder.execute_async()
    return first_row(resp) is not None


async def invoke_worker_or_rollback(
    supabase,
    *,
    session_id: UUID,
    user_id: UUID,
    organization_id: UUID,
    target: str,
    payload: dict[str, Any],
    rollback_values: dict[str, Any],
) -> None:
    """Dispatch the worker job; on failure roll the session status back and re-raise.

    `target` is a logical job name (see services/jobs/invoker.py), not a URL or an
    ARN — the transport is chosen by JOB_INVOKER.

    The rollback UPDATE is scoped to the caller. The original exception is
    re-raised so the calling service maps it to the right HTTP status (typically
    500) — this helper does not invent its own error type.
    """
    try:
        await get_invoker().invoke(target, payload)
    except Exception:
        logger.error(
            "intake_job_dispatch_failed_rolling_back",
            session_id=str(session_id),
            target=target,
        )
        await (
            supabase.table("intake_sessions")
            .update(rollback_values)
            .eq("id", str(session_id))
            .eq("user_id", str(user_id))
            .eq("organization_id", str(organization_id))
            .execute_async()
        )
        raise
