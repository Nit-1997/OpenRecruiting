import structlog

from src.model.ingestion import SourceRef
from src.model.packets import DecisionPacket, CandidateData, RequisitionData
from src.service.graph_ingestion_service import Triplet
from src.service.handlers.base_handler import BaseHandler

logger = structlog.get_logger(__name__)

STATUS_TO_EDGE: dict[str | None, str] = {
    "hired": "HIRED_BY",
    "rejected": "REJECTED_BY",
    "withdrawn": "WITHDREW_FROM",
}


class DecisionHandler(BaseHandler):
    async def fetch_and_build_triplets(self, source_ref: SourceRef, org_id: str) -> list[Triplet]:
        packet = await self._fetcher.fetch_decision_packet(source_ref.candidate_id)
        self._validate_org(packet.requisition.organization_id, org_id)
        return self._build_triplets(packet)

    def build_triplets_from_payload(self, payload: dict, org_id: str) -> list[Triplet]:
        packet = self._parse_packet(payload)
        return self._build_triplets(packet)

    def _parse_packet(self, payload: dict) -> DecisionPacket:
        return DecisionPacket(
            candidate=CandidateData(**payload["candidate"]),
            requisition=RequisitionData(
                id=payload["requisition"]["id"],
                role_title=payload["requisition"]["role_title"],
                organization_id=payload["requisition"].get("organization_id", ""),
                status=payload["requisition"].get("status"),
                experience_min_years=payload["requisition"].get("experience_min_years"),
                experience_max_years=payload["requisition"].get("experience_max_years"),
                role_location=payload["requisition"].get("role_location"),
                must_have_skills=payload["requisition"].get("must_have_skills") or [],
                nice_to_have_skills=payload["requisition"].get("nice_to_have_skills") or [],
            ),
        )

    def _build_triplets(self, packet: DecisionPacket) -> list[Triplet]:
        candidate = packet.candidate
        req = packet.requisition

        common = dict(
            source_name=candidate.name,
            source_type="Candidate",
            source_id=candidate.id,
            source_attributes={"name": candidate.name, "candidate_ref": candidate.id, "status": candidate.status},
            target_name=req.role_title,
            target_type="Requisition",
            target_id=req.id,
            target_attributes={
                "role_title": req.role_title,
                "status": req.status,
                "experience_min_years": req.experience_min_years,
                "experience_max_years": req.experience_max_years,
                "role_location": req.role_location,
            },
        )

        # Baseline pipeline membership — emitted for EVERY candidate so the graph
        # models the applicant pool, not just hired/rejected ones.
        triplets = [Triplet(
            **common,
            relation="APPLIED_TO",
            edge_attributes={"status": candidate.status},
        )]

        # Outcome edge — only when a decision has actually been made.
        edge_type = STATUS_TO_EDGE.get(candidate.status)
        if edge_type:
            triplets.append(Triplet(**common, relation=edge_type, edge_attributes={}))
        else:
            logger.info("candidate_in_pipeline_no_decision", status=candidate.status, candidate_id=candidate.id)

        return triplets
