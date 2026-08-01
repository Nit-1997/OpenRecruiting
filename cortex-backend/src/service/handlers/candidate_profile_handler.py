"""CandidateProfileHandler — attach Knit ATS enrichment edges onto an existing Candidate.

Synchronous `/ingest/direct` path (X-Internal-Secret) that backend's Knit
candidate-profile enrichment feature calls. The `candidate_profile_enriched` event
carries a parsed resume/profile and fans it out onto the EXISTING Candidate node
(keyed by `candidate_id`) as ontology-validated structured triplets:

    Candidate -[DEMONSTRATED]-> Skill   (per skill, evidence="resume")
    Candidate -[WORKED_AT]->    Company (per work_history entry with a company)
    Candidate -[EXPERIENCED_IN]-> Market (per domain)
    Candidate -[BASED_IN]->     Location (if location present)

Skill/Company/Market/Location are concept targets — they pass NO target_id and
canonicalize by name. Null/empty fields skip their edge group. There is no
Supabase rebuild for this payload (the enrichment is provided directly), so the
SQS-replay `fetch_and_build_triplets` path is unsupported, mirroring
RecruiterInsightHandler.
"""
from __future__ import annotations

import structlog

from src.model.ingestion import SourceRef
from src.service.graph_ingestion_service import Triplet
from src.service.handlers.base_handler import BaseHandler

logger = structlog.get_logger(__name__)


class CandidateProfileHandler(BaseHandler):
    async def fetch_and_build_triplets(self, source_ref: SourceRef, org_id: str) -> list[Triplet]:
        raise NotImplementedError(
            "CandidateProfileHandler only supports the direct payload path"
        )

    def build_triplets_from_payload(self, payload: dict, org_id: str) -> list[Triplet]:
        candidate_id = payload.get("candidate_id")
        candidate_name = payload.get("candidate_name") or candidate_id or ""
        if not candidate_id:
            logger.warning("candidate_profile_missing_candidate_id", org_id=org_id)
            return []

        candidate_source = {
            "source_name": candidate_name,
            "source_type": "Candidate",
            "source_id": candidate_id,
            "source_attributes": {
                "name": candidate_name,
                "candidate_ref": candidate_id,
                "status": payload.get("status"),
            },
        }

        triplets: list[Triplet] = []

        # Candidate -[DEMONSTRATED]-> Skill
        for skill in payload.get("skills") or []:
            if not skill:
                continue
            triplets.append(Triplet(
                **candidate_source,
                target_name=skill,
                target_type="Skill",
                target_attributes={"name": skill},
                relation="DEMONSTRATED",
                edge_attributes={"evidence": "resume"},
            ))

        # Candidate -[WORKED_AT]-> Company
        for entry in payload.get("work_history") or []:
            company = (entry.get("company") or "").strip()
            if not company:
                continue
            edge_attributes: dict = {}
            title = (entry.get("title") or "").strip()
            if title:
                edge_attributes["role_title"] = title
            highlights = [h for h in (entry.get("highlights") or []) if h]
            if highlights:
                edge_attributes["achievement"] = "; ".join(highlights)
            triplets.append(Triplet(
                **candidate_source,
                target_name=company,
                target_type="Company",
                target_attributes={"name": company},
                relation="WORKED_AT",
                edge_attributes=edge_attributes,
            ))

        # Candidate -[EXPERIENCED_IN]-> Market
        for domain in payload.get("domains") or []:
            if not domain:
                continue
            triplets.append(Triplet(
                **candidate_source,
                target_name=domain,
                target_type="Market",
                target_attributes={"name": domain},
                relation="EXPERIENCED_IN",
                edge_attributes={},
            ))

        # Candidate -[BASED_IN]-> Location
        location = (payload.get("location") or "").strip()
        if location:
            triplets.append(Triplet(
                **candidate_source,
                target_name=location,
                target_type="Location",
                target_attributes={"name": location},
                relation="BASED_IN",
                edge_attributes={},
            ))

        # Candidate -[APPLIED_TO]-> Requisition (baseline pipeline membership).
        # Requisition is keyed by its real id (target_id), so this edge attaches to
        # the same node any decision/plan ingestion uses — and materializes it if
        # it isn't in the graph yet.
        req_id = payload.get("requisition_id")
        req_title = (payload.get("requisition_title") or "").strip()
        if req_id and req_title:
            triplets.append(Triplet(
                **candidate_source,
                target_name=req_title,
                target_type="Requisition",
                target_id=req_id,
                target_attributes={
                    "role_title": req_title,
                    "status": payload.get("requisition_status"),
                },
                relation="APPLIED_TO",
                edge_attributes={
                    "stage": payload.get("stage"),
                    "status": payload.get("status"),
                    "applied_at": payload.get("applied_at"),
                    "source": "ats_sync",
                },
            ))

        logger.info(
            "candidate_profile_triplets_built",
            candidate_id=candidate_id,
            triplet_count=len(triplets),
            relation_counts={r: sum(1 for t in triplets if t.relation == r)
                             for r in {t.relation for t in triplets}},
        )
        return triplets
