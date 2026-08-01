"""DebriefConversationRepository — load/append turns for one debrief packet's chat.

One conversation row per packet (migration 122). Reads go through the custom
client's async surface (`single().execute_async()`); a missing row is a legitimate
empty result (PGRST116 -> None) that reads as [], not an error. Appends go through
the atomic, advisory-locked `debrief_conversation_append_turn` SECURITY DEFINER RPC
so concurrent turns serialize and the server stamps the turn's `idx`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.api.v2.core.rpc import call_rpc


class DebriefConversationRepository:
    def __init__(self, supabase) -> None:
        self._db = supabase

    async def load_turns(self, packet_id: str) -> list[dict]:
        """All turns for a packet's conversation, in order. [] when no row exists."""
        result = await (
            self._db.table("debrief_conversations")
            .select("turns")
            .eq("packet_id", packet_id)
            .single()
            .execute_async()
        )
        row = result.data
        if not row:
            return []
        return row.get("turns") or []

    async def append_turn(self, packet_id: str, turn: dict) -> dict:
        """Append a turn via the atomic append RPC; returns the turn with its `idx`.

        Each turn is stamped with a server-side `ts` (UTC ISO-8601) so the
        conversation GET endpoint can render real timestamps; turns persisted
        before this stamp simply lack the key (callers must tolerate that)."""
        stamped = {**turn, "ts": datetime.now(timezone.utc).isoformat()}
        return await call_rpc(
            self._db,
            "debrief_conversation_append_turn",
            {"p_packet_id": packet_id, "p_turn": stamped},
        )
