"""RecruiterInsightHandler — write a confirmed recruiter insight into the graph.

Synchronous `/ingest/direct` path (X-Internal-Secret) that backend's debrief
learning loop (spec §6) calls after a recruiter confirms an insight.

Payload contract:
    {
        "org_id": str,
        "requisition_id": str | None,
        "candidate_id": str | None,
        "kind": "decision_rationale" | "recruiter_preference",
        "insight_text": str,
        "triplet": {"subject": str, "predicate": str, "object": str} | None,
    }

- `decision_rationale` → `add_episode` (narrative rationale), mirroring
  `IntakeV2Handler._add_episode`. Best-effort: a Graphiti failure is logged and
  appended to `result.errors`, never raised.
- `recruiter_preference` with a `triplet` → a structured `Requisition -[VALUES]-> Trait`
  edge through `GraphIngestionService.ingest_triplets`, so it is ontology-validated
  like every other structured ingest. `VALUES`/`Trait` is the only ontology edge that
  fits "a recruiter expresses a preference for a requisition"; the recruiter's free-text
  `predicate` is preserved as `evidence` edge metadata.
- `recruiter_preference` WITHOUT a triplet (or with no `requisition_id`) → falls back to
  an episode so the insight is never silently dropped.
- Unknown `kind` → logged warning, no-op (no raise).
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog

from src.model.ingestion import SourceRef
from src.service.graph_ingestion_service import IngestionResult, Triplet
from src.service.handlers.base_handler import BaseHandler
from src.sync.provenance import Provenance

logger = structlog.get_logger(__name__)


class RecruiterInsightHandler(BaseHandler):
    async def fetch_and_build_triplets(self, source_ref: SourceRef, org_id: str) -> list[Triplet]:
        raise NotImplementedError("RecruiterInsightHandler only supports the direct payload path")

    def build_triplets_from_payload(self, payload: dict, org_id: str) -> list[Triplet]:
        raise NotImplementedError("RecruiterInsightHandler routes by kind in handle_direct")

    async def handle_direct(
        self,
        payload: dict,
        org_id: str,
        provenance: Provenance | None = None,
    ) -> IngestionResult:
        kind = payload.get("kind")
        insight_text = (payload.get("insight_text") or "").strip()
        requisition_id = payload.get("requisition_id")
        triplet = payload.get("triplet")

        if not insight_text:
            logger.warning("recruiter_insight_empty_text", org_id=org_id, kind=kind)
            return IngestionResult()

        if kind == "decision_rationale":
            return await self._add_episode(insight_text, org_id, requisition_id)

        if kind == "recruiter_preference":
            if triplet and requisition_id:
                return await self._ingest_preference(
                    triplet, org_id, requisition_id, insight_text, provenance
                )
            # No structured triplet (or no requisition to anchor it) — fall back to an
            # episode so the confirmed preference is never silently dropped.
            return await self._add_episode(insight_text, org_id, requisition_id)

        logger.warning("recruiter_insight_unknown_kind", org_id=org_id, kind=kind)
        return IngestionResult()

    async def _add_episode(
        self, insight_text: str, org_id: str, requisition_id: str | None
    ) -> IngestionResult:
        result = IngestionResult()
        name = f"recruiter_insight:{requisition_id or 'org'}"
        try:
            from graphiti_core.nodes import EpisodeType
            episode_type = EpisodeType.message
        except Exception:
            episode_type = None

        try:
            await self._ingestion_service._graphiti.add_episode(
                name=name,
                episode_body=insight_text,
                source_description=(
                    f"recruiter insight for requisition {requisition_id or 'org'}"
                ),
                reference_time=datetime.now(timezone.utc),
                group_id=org_id,
                **({"source": episode_type} if episode_type is not None else {}),
            )
            logger.info(
                "recruiter_insight_episode_added",
                org_id=org_id,
                requisition_id=requisition_id,
                content_length=len(insight_text),
            )
        except Exception as ep_err:
            logger.warning("recruiter_insight_episode_failed", org_id=org_id, error=str(ep_err))
            result.errors.append(f"episode write failed: {str(ep_err)[:200]}")
        return result

    async def _ingest_preference(
        self,
        triplet: dict,
        org_id: str,
        requisition_id: str,
        insight_text: str,
        provenance: Provenance | None,
    ) -> IngestionResult:
        subject = (triplet.get("subject") or "").strip() or requisition_id
        predicate = (triplet.get("predicate") or "").strip()
        obj = (triplet.get("object") or "").strip()
        if not obj:
            logger.warning("recruiter_insight_preference_no_object", org_id=org_id)
            return await self._add_episode(insight_text, org_id, requisition_id)

        structured = Triplet(
            source_name=subject,
            source_type="Requisition",
            source_id=requisition_id,
            source_attributes={"role_title": subject},
            target_name=obj,
            target_type="Trait",
            target_attributes={"name": obj},
            relation="VALUES",
            edge_attributes={"priority": "implicit", "evidence": predicate, "source": "debrief"},
        )
        return await self._ingestion_service.ingest_triplets(
            [structured], org_id, provenance=provenance
        )
