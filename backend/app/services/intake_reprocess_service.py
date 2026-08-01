"""IntakeReprocessService — re-run the context-builder Lambda with conversation
transcript folded in. 'Process till now' semantics per agent spec section 9.

Invariants:
  1. 409 when process_status='running' (no double-invoke).
  2. process_run_id bumped server-side, NOT passed to Lambda.
  3. Lambda payload exactly {"session_id": str, "include_turns": True}.
  4. On Lambda invoke failure, roll back process_status='failed' so the user can retry.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID, uuid4

import structlog

from app.services.jobs.invoker import CONTEXT_BUILDER
from app.services.intake._session_ops import (
    invoke_worker_or_rollback,
    load_owned_session,
    optimistic_flip,
)

logger = structlog.get_logger(__name__)


class IntakeReprocessError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class IntakeReprocessService:
    def __init__(self, supabase_client):
        self.supabase = supabase_client

    async def reprocess(
        self,
        session_id: UUID,
        user_id: UUID,
        organization_id: UUID,
    ) -> dict[str, Any]:
        row = await load_owned_session(
            self.supabase,
            session_id=session_id,
            user_id=user_id,
            organization_id=organization_id,
            columns="id,status,process_status,current_answers",
        )
        if not row:
            raise IntakeReprocessError(f"Session {session_id} not found", status_code=404)

        if row.get("process_status") == "running":
            raise IntakeReprocessError(
                "Reprocess already running for this session.", status_code=409,
            )

        process_run_id = uuid4()
        won = await optimistic_flip(
            self.supabase,
            session_id=session_id,
            user_id=user_id,
            organization_id=organization_id,
            values={
                "process_run_id": str(process_run_id),
                "process_status": "running",
                "process_stages": [],
                "process_error": None,
            },
            guards=[("eq", "process_status", "idle")],
        )
        if not won:
            raise IntakeReprocessError(
                "Reprocess already running (lost the race).", status_code=409,
            )

        try:
            await invoke_worker_or_rollback(
                self.supabase,
                session_id=session_id,
                user_id=user_id,
                organization_id=organization_id,
                target=CONTEXT_BUILDER,
                payload={"session_id": str(session_id), "include_turns": True},
                rollback_values={
                    "process_status": "failed",
                    "process_error": "Lambda invoke failed",
                },
            )
        except Exception as e:
            logger.error(
                "intake_reprocess_lambda_invoke_failed",
                session_id=str(session_id),
                error=str(e),
            )
            raise IntakeReprocessError(
                f"Failed to invoke reprocess Lambda: {e}", status_code=500,
            )

        logger.info(
            "intake_reprocess_triggered",
            session_id=str(session_id),
            process_run_id=str(process_run_id),
        )
        return {
            "session_id": str(session_id),
            "process_run_id": str(process_run_id),
        }
