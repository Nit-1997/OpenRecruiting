"""DebriefInsightService — durable-first recruiter-insight write-back (spec §6).

A confirmed insight is FIRST persisted to `debrief_insights` (sync_status='pending'),
THEN best-effort forwarded to cortex-backend. The recruiter's confirm must never
fail because Cortex is down, so any forward failure is swallowed and the row is left
'pending' (re-syncable). Dedup is on `(packet_id, content_hash)`: a duplicate
confirm returns the existing row without inserting or re-forwarding (idempotent).

Async-only Supabase (`execute_async`); the Cortex client raises UpstreamServiceError,
which is caught here.
"""

from __future__ import annotations

import hashlib

import structlog

from app.services.supabase import PostgrestError

logger = structlog.get_logger(__name__)

_TABLE = "debrief_insights"
_DEDUP_CONSTRAINT = "uq_debrief_insight_dedup"


def _is_dedup_violation(exc: PostgrestError) -> bool:
    """True only for the (packet_id, content_hash) unique-violation that two
    concurrent confirms of the same insight race into — SQLSTATE 23505 plus our
    constraint name. Any other PostgrestError must still propagate."""
    if exc.code != "23505":
        return False
    haystack = f"{exc.message or ''} {exc.details or ''}"
    return _DEDUP_CONSTRAINT in haystack


def _content_hash(text: str, kind: str, candidate_id: str | None) -> str:
    """Stable dedup hash over normalized text + kind + candidate_id."""
    norm = " ".join(text.split()).strip().lower()
    raw = f"{kind}|{candidate_id or ''}|{norm}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DebriefInsightService:
    def __init__(self, supabase, cortex_insight_client) -> None:
        self._db = supabase
        self._cortex = cortex_insight_client

    async def _read_existing(self, packet_id: str, content_hash: str) -> dict | None:
        """Idempotent dedup-hit shape for an already-persisted insight, or None."""
        existing = (
            await self._db.table(_TABLE)
            .select("id, sync_status")
            .eq("packet_id", packet_id)
            .eq("content_hash", content_hash)
            .single()
            .execute_async()
        )
        if not existing.data:
            return None
        return {
            "ok": True,
            "insight_id": existing.data["id"],
            "sync_status": existing.data.get("sync_status", "pending"),
        }

    async def log(
        self,
        *,
        packet_id: str,
        requisition_id: str | None,
        organization_id: str,
        created_by: str | None,
        candidate_id: str | None,
        kind: str,
        text: str,
        triplet: dict | None = None,
    ) -> dict:
        content_hash = _content_hash(text, kind, candidate_id)

        existing = await self._read_existing(packet_id, content_hash)
        if existing is not None:
            return existing

        row = {
            "packet_id": packet_id,
            "requisition_id": requisition_id,
            "organization_id": organization_id,
            "candidate_id": candidate_id,
            "kind": kind,
            "content": text,
            "content_hash": content_hash,
            "triplet": triplet,
            "sync_status": "pending",
            "created_by": created_by,
        }
        try:
            inserted = await self._db.table(_TABLE).insert(row).execute_async()
        except PostgrestError as exc:
            if not _is_dedup_violation(exc):
                raise
            # A concurrent confirm of the SAME insight won the race after our
            # pre-check missed. Its row (and its Cortex forward) already cover
            # this — return the winner's row idempotently, do NOT re-forward.
            winner = await self._read_existing(packet_id, content_hash)
            if winner is not None:
                return winner
            return {"ok": True, "insight_id": None, "sync_status": "pending"}
        insight_id = (inserted.data or {}).get("id")

        sync_status = "pending"
        try:
            await self._cortex.ingest(
                org_id=organization_id,
                requisition_id=requisition_id,
                candidate_id=candidate_id,
                kind=kind,
                insight_text=text,
                triplet=triplet,
            )
            sync_status = "synced"
        except Exception as exc:  # noqa: BLE001 — durable-first: never fail the confirm.
            logger.warning(
                "debrief_insight_cortex_forward_failed",
                insight_id=insight_id,
                error=str(exc),
            )

        if sync_status == "synced" and insight_id:
            await self._db.table(_TABLE).update({"sync_status": "synced"}).eq(
                "id", insight_id
            ).execute_async()

        return {"ok": True, "insight_id": insight_id, "sync_status": sync_status}
