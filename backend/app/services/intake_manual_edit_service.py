"""IntakeManualEditService — stamps manual_edit metadata + merges via RPC.

Per spec §6.6 B2.1: user edits always win against in-flight agent writes. We do
not coordinate with the voice agent's tool calls — the agent's next dynamic
prompt build will read the updated row and reflect the user's text.

Ownership: we re-check (session_id, user_id, organization_id) before mutating
even though RLS would also block, because RLS errors surface as generic 5xx
instead of clean 404s.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from app.api.v2.schemas.intake import PatchAnswerEntry
from app.services._supabase_rows import now_iso
from intake_core.persistence import aupdate_current_answers

logger = structlog.get_logger(__name__)


class IntakeManualEditService:
    def __init__(self, supabase_client):
        self.supabase = supabase_client

    async def apply_patch(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        organization_id: UUID,
        patch: dict[str, PatchAnswerEntry | dict[str, Any]],
    ) -> list[str]:
        """Validate ownership, stamp manual_edit metadata, merge into current_answers.

        Returns the list of qids applied, preserving caller-provided order.
        Raises LookupError on session-not-found / wrong org.
        """
        owner = await (
            self.supabase.table("intake_sessions")
            .select("id, user_id, organization_id")
            .eq("id", str(session_id))
            .eq("user_id", str(user_id))
            .eq("organization_id", str(organization_id))
            .single()
            .execute_async()
        )
        if not owner.data:
            raise LookupError(f"intake session {session_id} not found")

        edited_at = now_iso()
        rpc_patch: dict[str, dict[str, Any]] = {}
        applied: list[str] = []
        for qid, entry in patch.items():
            data = entry.model_dump(exclude_none=True) if isinstance(entry, PatchAnswerEntry) else {
                k: v for k, v in entry.items() if v is not None
            }
            stamped: dict[str, Any] = {
                "manual_edit": True,
                "edited_at": edited_at,
                "edited_by": str(user_id),
            }
            if "text" in data:
                stamped["text"] = data["text"]
            if "status" in data:
                stamped["status"] = data["status"]
            rpc_patch[qid] = stamped
            applied.append(qid)

        await aupdate_current_answers(self.supabase, str(session_id), rpc_patch)
        logger.info(
            "intake_manual_edit_applied",
            session_id=str(session_id),
            user_id=str(user_id),
            qids=applied,
        )
        return applied
