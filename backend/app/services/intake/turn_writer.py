"""Wrapper around intake_core.persistence.aappend_turn that assigns idx + timestamp.

Used by the text path (FastAPI / SupabaseAdminClient). Voice path can adopt this later.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from intake_core.persistence import aappend_turn


async def append_turn_for_session(
    supabase_client,
    session_id: str,
    role: str,
    content: str,
    modality: str,
    tool_calls: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Append a turn, assigning a monotonic idx and an ISO-8601 timestamp.

    Reads the current turns array length to compute idx. Returns the written
    turn dict (with idx + timestamp populated) so the caller can reference it
    (e.g., to pass turn_idx to coverage_tracker).
    """
    result = await (
        supabase_client.table("intake_sessions")
        .select("turns")
        .eq("id", session_id)
        .single()
        .execute_async()
    )
    existing = (result.data or {}).get("turns") or []
    next_idx = len(existing)

    turn: dict[str, Any] = {
        "idx": next_idx,
        "role": role,
        "content": content,
        "modality": modality,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if tool_calls:
        turn["tool_calls"] = tool_calls

    await aappend_turn(supabase_client, session_id, turn)
    return turn
