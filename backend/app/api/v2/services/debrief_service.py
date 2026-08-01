"""DebriefService — orchestrates debrief packet generation + the draft→save commit.

Generate flow (spec §9.1 + linkage spec §4.C2):
  1. Validate: dedup candidate_ids; 2–5 of them; every one belongs to the
     requisition (within the caller's org) AND is debrief-`ready`.
  2. `insert_generating` a placeholder row so the FE has a packet_id to poll.
  3. Call the stateless Cortex skill via CortexDebriefClient (inline await — the
     skill is ~seconds; acceptable for v1 per spec §9.1).
  4. On success: `finalize_draft` — the packet lands as a `draft` (previewable,
     NOT yet kept; NO supersede). The role packet list excludes drafts.
  5. On any failure: `mark_failed` with a STATIC message (never raw exception
     text), then re-raise a domain exception (never swallow → never a stuck row).

Save flow (linkage spec §4.C3):
  `save_draft` commits a `draft` → `fresh` via the atomic, advisory-locked
  `debrief_commit_draft` RPC (supersedes the prior fresh for the same natural key).
  An already-`fresh` packet is an idempotent no-op; `generating`/`failed`/
  `superseded` are 409 conflicts; a missing/cross-org packet is 404.

Eligibility tiering itself lives in DebriefRepository (`candidates_for_role`);
this service consumes those tiers to gate the generate. The router stays thin and
delegates picker reads straight to the repository.
"""

from __future__ import annotations

from app.api.v2.core.exceptions import (
    ConflictError,
    NotFoundError,
    UpstreamServiceError,
    ValidationError,
)
import structlog

from app.api.v2.services.cortex_debrief_client import CortexDebriefClient
from app.api.v2.services.debrief_repository import DebriefRepository

logger = structlog.get_logger(__name__)

_MIN_CANDIDATES = 2
_MAX_CANDIDATES = 5
_FAILED_MESSAGE = "Debrief generation failed — please try again."
_SAVE_CONFLICT_MESSAGE = (
    "This debrief can't be saved in its current state — regenerate it first."
)


class DebriefService:
    def __init__(
        self,
        *,
        repository: DebriefRepository,
        cortex_client: CortexDebriefClient,
    ) -> None:
        self._repo = repository
        self._cortex = cortex_client

    async def generate(
        self,
        *,
        org_id: str,
        requisition_id: str,
        candidate_ids: list[str],
        created_by: str | None,
    ) -> dict:
        """Validate, persist `generating`, call the skill, finalize as a `draft`.

        Returns `{"packet_id", "status": "draft"}` — the FE previews the packet,
        then commits it via POST /packets/{id}/save. Raises ValidationError (400)
        on a bad candidate set, UpstreamServiceError (502) if the skill or finalize
        fails."""
        unique_ids = self._dedup(candidate_ids)
        await self._validate(org_id, requisition_id, unique_ids)

        packet_id = await self._repo.insert_generating(
            requisition_id=requisition_id,
            organization_id=org_id,
            created_by=created_by,
            candidate_ids=unique_ids,
        )

        # Both the Cortex skill call AND the finalize (finalize_draft) are inside ONE
        # try/except. If EITHER fails the row must be flipped out of `generating`
        # (never left stuck) and the client must see a STATIC message — finalize_draft
        # can surface a PostgrestError/UpstreamServiceError whose detail carries raw
        # SQLSTATE + pg text; that raw text MUST NOT escape to the client.
        try:
            packet = await self._cortex.generate(
                org_id=org_id,
                requisition_id=requisition_id,
                candidate_ids=unique_ids,
            )
            # The Cortex PacketBuilder stamps its OWN id on the body (a uuid != our
            # generating-row id). Overwrite it with the row id so the persisted packet
            # is self-consistent and addressable by the SAME id /generate returns and
            # /save + GET /packets/{id} key on — otherwise those 404 (live-DB bug).
            packet["id"] = str(packet_id)
            await self._repo.finalize_draft(packet_id, packet)
        except Exception as exc:  # noqa: BLE001 — must always mark_failed + re-raise
            await self._repo.mark_failed(packet_id, _FAILED_MESSAGE)
            # Log the raw error server-side ONLY — never in the client response.
            logger.warning(
                "debrief_generation_failed",
                packet_id=packet_id,
                requisition_id=requisition_id,
                error=str(exc),
            )
            # Re-raise a domain exception with a STATIC client message. We do NOT
            # bubble the original V2DomainError unchanged because its detail may
            # carry raw SQLSTATE/pg text.
            raise UpstreamServiceError(_FAILED_MESSAGE) from exc

        logger.info(
            "debrief_generated_draft",
            packet_id=packet_id,
            requisition_id=requisition_id,
            candidate_count=len(unique_ids),
        )
        return {"packet_id": packet_id, "status": "draft"}

    async def save_draft(self, *, org_id: str, packet_id: str) -> dict:
        """Commit a draft packet to `fresh` (linkage spec §4.C3).

        Loads the packet org-scoped, then branches on its status:
          - missing/cross-org → NotFoundError (404)
          - already `fresh`    → idempotent ok ({packet_id, status:'fresh'})
          - `draft`            → commit_draft RPC → {packet_id, status:'fresh'}
          - anything else (`generating`/`failed`/`superseded`) → ConflictError (409)

        Static client messages only — no raw exception/SQLSTATE leak."""
        row = await self._repo.get_packet(packet_id, org_id)
        if not row:
            raise NotFoundError("Debrief packet not found")

        status = row.get("status")
        if status == "fresh":
            # Idempotent: a second save (e.g. a retried request) is a no-op success.
            return {"packet_id": packet_id, "status": "fresh"}
        if status != "draft":
            # generating / failed / superseded — not a committable state.
            raise ConflictError("DEBRIEF_NOT_DRAFT", _SAVE_CONFLICT_MESSAGE)

        await self._repo.commit_draft(packet_id)
        logger.info(
            "debrief_draft_saved",
            packet_id=packet_id,
            organization_id=org_id,
        )
        return {"packet_id": packet_id, "status": "fresh"}

    # ------------------------------------------------------------------ #
    @staticmethod
    def _dedup(candidate_ids: list[str]) -> list[str]:
        """De-dup while preserving first-seen order."""
        seen: set[str] = set()
        out: list[str] = []
        for cid in candidate_ids:
            if cid and cid not in seen:
                seen.add(cid)
                out.append(cid)
        return out

    async def _validate(
        self, org_id: str, requisition_id: str, candidate_ids: list[str]
    ) -> None:
        if not (_MIN_CANDIDATES <= len(candidate_ids) <= _MAX_CANDIDATES):
            raise ValidationError(
                f"Select between {_MIN_CANDIDATES} and {_MAX_CANDIDATES} candidates"
            )

        eligible = await self._repo.candidates_for_role(requisition_id, org_id)
        by_id = {c.candidate_id: c for c in eligible}

        for cid in candidate_ids:
            item = by_id.get(cid)
            if item is None:
                # Unknown / foreign / cross-org candidate for this requisition.
                raise ValidationError(
                    "One or more selected candidates do not belong to this role"
                )
            if item.eligibility != "ready":
                raise ValidationError(
                    "One or more selected candidates are not ready for a debrief "
                    "(need at least one completed, rated round)"
                )

        # Parity gate (spec 2026-06-08 §5): the debrief averages each candidate over
        # their rated rounds, so comparing candidates with a DIFFERENT number of
        # rated rounds is unfair. Require all selected to share the same count.
        rated_counts = {by_id[cid].rated_round_count for cid in candidate_ids}
        if len(rated_counts) > 1:
            raise ValidationError(
                "Select candidates who have completed the same number of rated "
                "rounds (e.g. 3 each) — comparing different counts isn't fair"
            )
