"""Read + persist per-round screening configuration.

The save path goes through the `screening_save_config` RPC (migration 115) so
the config upsert + questions-replace happen in one transaction. `get` /
`set_enabled` are plain table reads/updates against the custom async Supabase
client (execute_async, never the sync .execute twin).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.api.v2.core.rpc import call_rpc
from app.api.v2.schemas.screening import ScreeningConfig


class ScreeningConfigService:
    def __init__(self, supabase):
        self.supabase = supabase

    async def get(self, round_id: str) -> dict | None:
        """Return the config + its questions (ordered) for a round, or None."""
        cfg_result = await (
            self.supabase.table("round_screening_configs")
            .select("*")
            .eq("round_id", round_id)
            .single()
            .execute_async()
        )
        config = cfg_result.data
        if not config:
            return None

        questions_result = await (
            self.supabase.table("round_screening_questions")
            .select("*")
            .eq("round_screening_config_id", config["id"])
            .order("order_index")
            .execute_async()
        )
        config["questions"] = questions_result.data or []
        return config

    async def upsert(
        self, cfg: ScreeningConfig, *, requisition_id: str, created_by: str
    ) -> dict:
        """Atomic config upsert + questions replace via the RPC."""
        payload = {
            "round_id": cfg.round_id,
            "requisition_id": requisition_id,
            "created_by": created_by,
            "enabled": cfg.enabled,
            "voice": cfg.voice,
            "follow_up_style": cfg.follow_up_style,
            "est_duration_minutes": cfg.est_duration_minutes,
            "validity_days": cfg.validity_days,
            "deploy_scope": cfg.deploy_scope,
            "questions": [
                {
                    "order_index": q.order_index,
                    "title": q.title,
                    "prompt": q.prompt,
                    "probe": q.probe,
                    "signal": q.signal,
                    "dimension": q.dimension,
                    "duration_minutes": q.duration_minutes,
                }
                for q in cfg.questions
            ],
        }
        data = await call_rpc(self.supabase, "screening_save_config", {"p": payload})
        return data or {}

    async def set_enabled(self, round_id: str, enabled: bool) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        await (
            self.supabase.table("round_screening_configs")
            .update({"enabled": enabled, "updated_at": now})
            .eq("round_id", round_id)
            .execute_async()
        )
        return {"round_id": round_id, "enabled": enabled}

    async def set_persona(
        self, round_id: str, persona_id: str | None, persona_snapshot: dict
    ) -> dict:
        """Attach a resolved persona to the round's screening config so the voice
        agent reads it (round_screening_configs.persona_snapshot is the Phase-1
        seam). No-op if no config row exists yet — the recruiter must save a
        config first; we never crash here."""
        now = datetime.now(timezone.utc).isoformat()
        await (
            self.supabase.table("round_screening_configs")
            .update(
                {
                    "persona_id": persona_id,
                    "persona_snapshot": persona_snapshot,
                    "updated_at": now,
                }
            )
            .eq("round_id", round_id)
            .execute_async()
        )
        return {"round_id": round_id, "persona_id": persona_id}
