"""Proactive "OpenRecruiting sees recurring gaps — add a screen?" suggestion.

The founder flow: a recruiter "later decides to add screening after seeing gaps
in a few interviews." This service surfaces that proactively. It reads recurring
candidate weaknesses for ONE role from Cortex (via CortexGapReader) and decides
whether to nudge the recruiter to add a screening round that could catch the gap
earlier.

FAIL SAFE is the whole point — no suggestion is always an acceptable result:
  - cold start / empty Cortex / reader exception  -> should_suggest=False
  - gap is not actually recurring (< N candidates) -> should_suggest=False
  - the role has no rounds                          -> should_suggest=False
  - a screen is ALREADY enabled on the role         -> suppressed (False)
We never raise into the route; a failed read must show no banner, not error the
dashboard.
"""

from __future__ import annotations

import structlog

from .cortex_gap_reader import CortexGapReader

logger = structlog.get_logger(__name__)

# A competency is a "recurring" gap only when at least this many DISTINCT
# candidates on the role were flagged weak in it. One candidate is not a pattern.
_RECURRING_THRESHOLD = 2


class ScreeningSuggestionService:
    def __init__(self, supabase):
        self.supabase = supabase
        self.reader = CortexGapReader()

    async def suggest(
        self, *, requisition_id: str, org_id: str, org_name: str
    ) -> dict:
        """Return {should_suggest, reason, target_round_id}. Never raises."""
        no = {"should_suggest": False, "reason": "", "target_round_id": None}
        try:
            # Suppress if a screen is already enabled anywhere on this role —
            # the recruiter already acted; no need to nudge.
            if await self._has_enabled_screen(requisition_id):
                return no

            gaps = await self.reader.read_recurring_gaps(
                org_id=org_id, org_name=org_name, requisition_id=requisition_id
            )
            top = self._dominant_gap(gaps)
            if top is None:
                return no

            target_round_id = await self._first_round_id(requisition_id)
            if target_round_id is None:
                # Nowhere to attach a screen — no actionable suggestion.
                return no

            competency, count = top
            reason = (
                f"{count} candidates were repeatedly weak in {competency} — "
                f"an earlier screening round could catch this before the panel."
            )
            return {
                "should_suggest": True,
                "reason": reason,
                "target_round_id": target_round_id,
            }
        except Exception as exc:  # noqa: BLE001 — fail safe: never break the dashboard
            logger.warning("screening_suggestion_failed", error=str(exc))
            return no

    def _dominant_gap(self, gaps: list[dict]) -> tuple[str, int] | None:
        """The biggest recurring gap (competency, weak_candidate_count), or None
        when nothing clears the recurring threshold. Rows arrive biggest-first
        from Cortex; we still re-check defensively."""
        best: tuple[str, int] | None = None
        for row in gaps:
            competency = str(row.get("competency") or "").strip()
            try:
                count = int(row.get("weak_candidates") or 0)
            except (TypeError, ValueError):
                continue
            if not competency or count < _RECURRING_THRESHOLD:
                continue
            if best is None or count > best[1]:
                best = (competency, count)
        return best

    async def _has_enabled_screen(self, requisition_id: str) -> bool:
        """True if any round of this requisition already has an enabled screen."""
        result = await (
            self.supabase.table("round_screening_configs")
            .select("id")
            .eq("requisition_id", requisition_id)
            .eq("enabled", True)
            .execute_async()
        )
        return bool(result.data)

    async def _first_round_id(self, requisition_id: str) -> str | None:
        """The role's first round (lowest round_number) — where a new screen
        would attach to catch the gap earliest. None if the role has no rounds."""
        result = await (
            self.supabase.table("rounds")
            .select("id, round_number")
            .eq("requisition_id", requisition_id)
            .is_null("deleted_at")
            .order("round_number")
            .execute_async()
        )
        rows = result.data or []
        if not rows:
            return None
        return rows[0].get("id")
