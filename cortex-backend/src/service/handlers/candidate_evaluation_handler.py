"""CandidateEvaluationHandler — ingest an ATS interviewer scorecard onto the graph.

Direct-only (/ingest/direct, X-Internal-Secret). Emits, per evaluation:
    Interviewer -[EVALUATED]-> Candidate   (interviewer + candidate keyed by real ids)
    Candidate   -[ASSESSED_ON]-> Competency (per rated attribute; round_rating + feedback_text)
Interviewer/Candidate are deterministic-id nodes (pass source_id/target_id, non-concept
type). Competency is a concept target (no target_id → name-canonicalized). round_rating
values are pre-normalized upstream to the ontology literal set."""
from __future__ import annotations

import structlog

from src.model.ingestion import SourceRef
from src.service.graph_ingestion_service import Triplet
from src.service.handlers.base_handler import BaseHandler

logger = structlog.get_logger(__name__)

_VALID_RATINGS = {"strong_yes", "yes", "maybe", "no", "strong_no"}


class CandidateEvaluationHandler(BaseHandler):
    async def fetch_and_build_triplets(self, source_ref: SourceRef, org_id: str) -> list[Triplet]:
        raise NotImplementedError("CandidateEvaluationHandler only supports the direct payload path")

    def build_triplets_from_payload(self, payload: dict, org_id: str) -> list[Triplet]:
        candidate_id = payload.get("candidate_id")
        candidate_name = payload.get("candidate_name") or candidate_id or ""
        if not candidate_id:
            logger.warning("candidate_evaluation_missing_candidate_id", org_id=org_id)
            return []

        candidate_node = {
            "name": candidate_name,
            "candidate_ref": candidate_id,
            "status": payload.get("status"),
        }
        triplets: list[Triplet] = []

        for ev in payload.get("evaluations") or []:
            interviewer_id = ev.get("interviewer_id")
            if interviewer_id:
                triplets.append(Triplet(
                    source_name=ev.get("interviewer_name") or interviewer_id,
                    source_type="Interviewer",
                    source_id=interviewer_id,
                    source_attributes={"interviewer_ref": interviewer_id},
                    target_name=candidate_name,
                    target_type="Candidate",
                    target_id=candidate_id,
                    target_attributes=candidate_node,
                    relation="EVALUATED",
                    edge_attributes={
                        "recommendation": ev.get("recommendation"),
                        "interview_id": ev.get("interview_id"),
                        "submitted_at": ev.get("submitted_at"),
                        "source": "ats_scorecard",
                    },
                ))

            for attr in ev.get("attributes") or []:
                name = (attr.get("name") or "").strip()
                if not name:
                    continue
                rating = attr.get("rating")
                round_rating = rating if rating in _VALID_RATINGS else None
                triplets.append(Triplet(
                    source_name=candidate_name,
                    source_type="Candidate",
                    source_id=candidate_id,
                    source_attributes=candidate_node,
                    target_name=name,
                    target_type="Competency",
                    target_attributes={"heading": name},
                    relation="ASSESSED_ON",
                    edge_attributes={
                        "evidence_status": "from_rating",
                        "round_rating": round_rating,
                        "feedback_text": attr.get("note"),
                    },
                ))

        logger.info("candidate_evaluation_triplets_built",
                    candidate_id=candidate_id, triplet_count=len(triplets))
        return triplets
