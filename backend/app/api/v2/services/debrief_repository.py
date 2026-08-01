"""DebriefRepository — all Supabase reads/writes for the debrief feature.

Every DB access goes through the custom client's async surface
(`execute_async` / `count_async` / `rpc` via `call_rpc`). The sync `.execute()`
twin is NEVER called here (it blocks the event loop). Multi-row status flips
(supersede prior `fresh` + finalize this row) go through the atomic
`debrief_supersede_and_insert` SECURITY DEFINER RPC (migration 119), not a Python
loop of awaited UPDATEs.

Eligibility tiering (spec §7) is pure Python over the embedded
candidate_rounds -> candidate_feedback join — PostgREST can't express "candidate
has >= 1 completed round WITH >= 1 feedback row" as a single filterable predicate,
so we fetch the nested rows and classify (+ count the signal) here.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

import structlog

from app.api.v2.core.exceptions import UpstreamServiceError
from app.api.v2.core.rpc import call_rpc
from app.models.debrief import (
    CandidatePickItem,
    CandidateSignal,
    EligibilityTier,
    PacketListItem,
    RolePickItem,
)

logger = structlog.get_logger(__name__)

# candidate_rounds.processing_status value that signals the round is done.
_COMPLETED_PROCESSING = "completed"

# candidate_rounds.rating values that score (spec 2026-06-08 §2). A `ready` tier
# needs >= _MIN_RATED_ROUNDS completed rounds carrying one of these — the rating IS
# the scoring signal, so a completed round without a rating is not scorable.
_VALID_RATINGS = frozenset({"strong_yes", "yes", "maybe", "no", "strong_no"})
_MIN_RATED_ROUNDS = 1

# A generous cap on the candidate scan for the pickers — orgs don't realistically
# have thousands of active candidates per role, and the eligibility classification
# is cheap. Keeps an unbounded fetch off the event loop.
_PICKER_SCAN_LIMIT = 2000


class DebriefRepository:
    def __init__(self, supabase) -> None:
        self._db = supabase

    # ------------------------------------------------------------------ #
    # Eligibility classification (pure)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _round_feedback(round_: dict) -> list[dict]:
        """The candidate_feedback rows embedded on one candidate_rounds row."""
        return round_.get("candidate_feedback") or []

    @staticmethod
    def _eligibility(rounds: list[dict]) -> EligibilityTier:
        """Classify a candidate's eligibility tier from its candidate_rounds
        (spec 2026-06-08 §5 — rating-based).

        ready           — >= _MIN_RATED_ROUNDS completed rounds carrying a valid
                          `rating` (the scoring signal).
        awaiting_signal — has rounds, but fewer than the minimum are completed+rated.
        early_stage     — no rounds at all.
        """
        if not rounds:
            return "early_stage"
        if DebriefRepository._rated_round_count(rounds) >= _MIN_RATED_ROUNDS:
            return "ready"
        return "awaiting_signal"

    @staticmethod
    def _rounds_completed(rounds: list[dict]) -> int:
        return sum(
            1 for r in rounds if r.get("processing_status") == _COMPLETED_PROCESSING
        )

    @staticmethod
    def _rated_round_count(rounds: list[dict]) -> int:
        """Completed rounds carrying a valid `rating` — the rounds the debrief
        averages over. The parity gate requires this to match across the selected
        candidates (spec 2026-06-08 §5)."""
        return sum(
            1
            for r in rounds
            if r.get("processing_status") == _COMPLETED_PROCESSING
            and r.get("rating") in _VALID_RATINGS
        )

    @staticmethod
    def _signal(rounds: list[dict]) -> CandidateSignal:
        """Aggregate the feedback signal across ALL of a candidate's rounds.

        feedback_count        — total candidate_feedback rows.
        evidence_backed_count — those whose evidence_status is non-null (graded).
        """
        feedback_count = 0
        evidence_backed = 0
        for r in rounds:
            for fb in DebriefRepository._round_feedback(r):
                feedback_count += 1
                if fb.get("evidence_status") is not None:
                    evidence_backed += 1
        return CandidateSignal(
            feedback_count=feedback_count,
            evidence_backed_count=evidence_backed,
        )

    # ------------------------------------------------------------------ #
    # Pickers
    # ------------------------------------------------------------------ #
    async def _scan_candidates(self, org_id: str, requisition_id: str | None) -> list[dict]:
        """Fetch active candidates (optionally for one req) with their requisition
        identity + embedded candidate_rounds, then drop any whose requisition is
        cross-org or soft-deleted (defence-in-depth on top of RLS)."""
        query = (
            self._db.table("candidates")
            .select(
                "id, name, requisition_id, "
                "requisitions(id, role_title, organization_id, deleted_at), "
                # Nested embed: each round carries its rating (the scoring signal,
                # for eligibility + rated_round_count) and its candidate_feedback
                # rows (for the signal counts) so the classification is a pure pass
                # over the response — no per-candidate follow-up query.
                "candidate_rounds(processing_status, status, rating, "
                "candidate_feedback(evidence_status))"
            )
            .eq("status", "active")
            .is_null("deleted_at")
            .limit(_PICKER_SCAN_LIMIT)
        )
        if requisition_id is not None:
            query = query.eq("requisition_id", requisition_id)
        result = await query.execute_async()
        rows = result.data or []
        scoped: list[dict] = []
        for row in rows:
            req = row.get("requisitions") or {}
            if req.get("organization_id") != org_id or req.get("deleted_at") is not None:
                continue
            scoped.append(row)
        return scoped

    async def candidates_for_role(
        self, requisition_id: str, org_id: str
    ) -> list[CandidatePickItem]:
        """All active candidates on a role, each tagged with its eligibility tier."""
        rows = await self._scan_candidates(org_id, requisition_id)
        items: list[CandidatePickItem] = []
        for row in rows:
            rounds = row.get("candidate_rounds") or []
            items.append(
                CandidatePickItem(
                    candidate_id=row["id"],
                    name=row.get("name") or "",
                    eligibility=self._eligibility(rounds),
                    rounds_completed=self._rounds_completed(rounds),
                    rounds_total=len(rounds),
                    rated_round_count=self._rated_round_count(rounds),
                    signal=self._signal(rounds),
                )
            )
        return items

    async def roles_with_eligible_candidates(self, org_id: str) -> list[RolePickItem]:
        """Roles that can actually be debriefed: >= 2 `ready` candidates sharing the
        SAME `rated_round_count` (spec 2026-06-08 §5). Because generate enforces
        round-count parity, a role with 2 ready candidates of DIFFERENT counts can't
        be debriefed — so it isn't offered. `eligible_candidate_count` is the size
        of the largest parity-matched ready group (the comparable set)."""
        rows = await self._scan_candidates(org_id, requisition_id=None)
        by_req: dict[str, dict] = {}
        for row in rows:
            req = row.get("requisitions") or {}
            req_id = req.get("id") or row.get("requisition_id")
            if not req_id:
                continue
            rounds = row.get("candidate_rounds") or []
            if self._eligibility(rounds) != "ready":
                continue
            bucket = by_req.setdefault(
                req_id, {"role_title": req.get("role_title") or "", "counts": Counter()}
            )
            bucket["counts"][self._rated_round_count(rounds)] += 1

        items: list[RolePickItem] = []
        for req_id, info in by_req.items():
            largest_group = max(info["counts"].values(), default=0)
            if largest_group >= 2:
                items.append(
                    RolePickItem(
                        requisition_id=req_id,
                        role_title=info["role_title"],
                        eligible_candidate_count=largest_group,
                    )
                )
        return items

    # ------------------------------------------------------------------ #
    # Packet lifecycle
    # ------------------------------------------------------------------ #
    async def insert_generating(
        self,
        *,
        requisition_id: str,
        organization_id: str,
        created_by: str | None,
        candidate_ids: list[str],
    ) -> str:
        """Insert a placeholder `generating` row and return its id (so the FE has
        a packet_id to poll while the Cortex skill runs)."""
        payload = {
            "requisition_id": requisition_id,
            "organization_id": organization_id,
            "created_by": created_by,
            "candidate_ids": candidate_ids,
            "status": "generating",
        }
        result = await self._db.table("debrief_packets").insert(payload).execute_async()
        data = result.data or {}
        if not data or "id" not in data:
            # PostgREST returned a 2xx with an unexpected/empty body — surface a
            # clean domain 502 instead of a bare KeyError → catch-all 500.
            raise UpstreamServiceError("Failed to create debrief packet")
        return data["id"]

    async def supersede_and_insert(self, *, packet_id: str, packet: dict) -> dict:
        """Atomically supersede prior `fresh` packets for the same (req, candidate
        SET) and finalize this row to `fresh` with the packet JSONB. One RPC.

        Legacy direct-to-fresh finalize. The draft→save lifecycle uses
        `finalize_draft` (generate) + `commit_draft` (save) instead."""
        return await call_rpc(
            self._db,
            "debrief_supersede_and_insert",
            {"p": {"packet_id": packet_id, "packet": packet}},
        )

    async def finalize_draft(self, packet_id: str, packet: dict) -> None:
        """Finalize a `generating` row to `draft` with the packet JSONB.

        Non-superseding: a draft is a previewable-but-not-yet-kept packet, excluded
        from the role packet list. The explicit save (`commit_draft`) is what
        supersedes the prior `fresh` and flips this row to `fresh`. `generated_at`
        is stamped here because the body exists from this point on."""
        now_iso = datetime.now(timezone.utc).isoformat()
        await (
            self._db.table("debrief_packets")
            .update(
                {
                    "status": "draft",
                    "packet": packet,
                    "generation_error": None,
                    "generated_at": now_iso,
                    "updated_at": now_iso,
                }
            )
            .eq("id", packet_id)
            .execute_async()
        )

    async def commit_draft(self, packet_id: str) -> None:
        """Commit a `draft` row to `fresh` via the atomic, advisory-locked
        `debrief_commit_draft` RPC (migration 121): supersede the prior `fresh`
        packet for the same natural key, then flip this draft row to `fresh`."""
        await call_rpc(
            self._db,
            "debrief_commit_draft",
            {"p_packet_id": packet_id},
        )

    async def mark_failed(self, packet_id: str, error: str) -> None:
        """Flip a `generating` row to `failed` with a static error message.

        NOTE: `error` is a service-authored static string — never raw exception
        text — to honor the 'no str(e) in client-readable state' invariant."""
        await (
            self._db.table("debrief_packets")
            .update({"status": "failed", "generation_error": error})
            .eq("id", packet_id)
            .execute_async()
        )

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    async def get_packet(self, packet_id: str, org_id: str) -> dict | None:
        """Fetch one packet row, org-scoped. None when missing or cross-org."""
        result = await (
            self._db.table("debrief_packets")
            .select("*")
            .eq("id", packet_id)
            .eq("organization_id", org_id)
            .single()
            .execute_async()
        )
        return result.data

    async def list_packets(self, requisition_id: str, org_id: str) -> list[PacketListItem]:
        """Role-tab packet list, newest first (spec §9.1).

        Only committed packets are listed: drafts (previewed-but-not-kept),
        `generating`, and `failed` rows are excluded so the role tab shows just
        the fresh + superseded history."""
        result = await (
            self._db.table("debrief_packets")
            .select("id, status, candidate_ids, packet, generated_at, created_at")
            .eq("requisition_id", requisition_id)
            .eq("organization_id", org_id)
            .in_("status", ["fresh", "superseded"])
            .order("created_at", desc=True)
            .execute_async()
        )
        rows = result.data or []
        items: list[PacketListItem] = []
        for row in rows:
            packet = row.get("packet") or {}
            items.append(
                PacketListItem(
                    packet_id=row["id"],
                    status=row["status"],
                    candidate_ids=row.get("candidate_ids") or [],
                    verdict=packet.get("verdict"),
                    confidence=packet.get("confidence"),
                    generated_at=row.get("generated_at"),
                    created_at=row["created_at"],
                )
            )
        return items
