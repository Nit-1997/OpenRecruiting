"""CandidateDecisionService — org-scoped verdict + round-outcome writes.

The org-scoped recruiter twins of the staff-only admin candidate routes (spec §4).
The admin routes lean on `require_staff` + the service-role client; these
methods instead re-scope ownership to the caller's `org_id` before writing
(candidate -> requisition -> organization_id), so they carry the recruiter trust
boundary. Exposed only through the debrief `/actions` endpoint in V1; the admin
routes are untouched.

Async-only Supabase (`execute_async`). Domain exceptions bubble to the global
handlers — no raw exception text leaves the service.
"""

from __future__ import annotations

from uuid import UUID

from app.api.v2.core.exceptions import NotFoundError, ValidationError
from app.api.v2.services.journey_service import load_cr_with_round_for_org

_VALID_VERDICTS = frozenset({"strong_hire", "hire", "no_hire", "strong_no_hire"})
_VALID_STATUSES = frozenset({"active", "hired", "rejected", "withdrawn"})
_VALID_OUTCOMES = frozenset({"advance", "reject", "hold"})


class CandidateDecisionService:
    def __init__(self, supabase) -> None:
        self._db = supabase

    async def set_verdict(
        self, candidate_id: str, verdict: str, status: str | None, org_id: str
    ) -> dict:
        """Write `candidates.final_verdict` (+ optional `status`), org-scoped.

        Cross-org / missing candidate -> NotFoundError; bad enum -> ValidationError.
        """
        if verdict not in _VALID_VERDICTS:
            raise ValidationError(f"Invalid verdict: {verdict}")
        if status is not None and status not in _VALID_STATUSES:
            raise ValidationError(f"Invalid status: {status}")

        result = await (
            self._db.table("candidates")
            .select("id, final_verdict, status, requisitions(organization_id, deleted_at)")
            .eq("id", str(candidate_id))
            .is_null("deleted_at")
            .single()
            .execute_async()
        )
        candidate = result.data
        if not candidate:
            raise NotFoundError("Candidate not found")
        req = candidate.get("requisitions") or {}
        if req.get("organization_id") != org_id or req.get("deleted_at") is not None:
            raise NotFoundError("Candidate not found")

        update: dict = {"final_verdict": verdict}
        if status is not None:
            update["status"] = status
        updated = await (
            self._db.table("candidates")
            .update(update)
            .eq("id", str(candidate_id))
            .execute_async()
        )
        row = updated.data
        return row[0] if isinstance(row, list) else (row or {})

    async def set_round_outcome(self, cr_id: str, outcome: str, org_id: str) -> dict:
        """Write `candidate_rounds.outcome`, org-scoped.

        Ownership is enforced by `load_cr_with_round_for_org` (candidate_round ->
        candidate -> requisition -> org), which raises NotFoundError on cross-org or
        missing. Bad enum -> ValidationError.
        """
        if outcome not in _VALID_OUTCOMES:
            raise ValidationError(f"Invalid outcome: {outcome}")

        await load_cr_with_round_for_org(self._db, UUID(str(cr_id)), org_id)

        updated = await (
            self._db.table("candidate_rounds")
            .update({"outcome": outcome})
            .eq("id", str(cr_id))
            .execute_async()
        )
        row = updated.data
        return row[0] if isinstance(row, list) else (row or {})
