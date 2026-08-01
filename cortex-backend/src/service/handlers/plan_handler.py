import structlog

from src.model.ingestion import SourceRef
from src.model.packets import PlanPacket, RequisitionData, RoundWithCompetenciesData
from src.ontology.normalizers import normalize_round_category, normalize_competency
from src.service.graph_ingestion_service import Triplet
from src.service.handlers.base_handler import BaseHandler

logger = structlog.get_logger(__name__)


class PlanHandler(BaseHandler):
    async def fetch_and_build_triplets(self, source_ref: SourceRef, org_id: str) -> list[Triplet]:
        packet = await self._fetcher.fetch_plan_packet(source_ref.requisition_id)
        self._validate_org(packet.requisition.organization_id, org_id)
        return self._build_triplets(packet)

    def build_triplets_from_payload(self, payload: dict, org_id: str) -> list[Triplet]:
        packet = self._parse_packet(payload)
        return self._build_triplets(packet)

    def _parse_packet(self, payload: dict) -> PlanPacket:
        req = payload["requisition"]
        return PlanPacket(
            requisition=RequisitionData(
                id=req["id"],
                role_title=req["role_title"],
                organization_id=req.get("organization_id", ""),
                organization_name=req.get("organization_name"),
                organization_domain=req.get("organization_domain"),
                status=req.get("status"),
                experience_min_years=req.get("experience_min_years"),
                experience_max_years=req.get("experience_max_years"),
                role_location=req.get("role_location"),
                must_have_skills=req.get("must_have_skills") or [],
                nice_to_have_skills=req.get("nice_to_have_skills") or [],
            ),
            rounds=[
                RoundWithCompetenciesData(
                    id=r["id"],
                    name=r["name"],
                    category=r.get("category"),
                    duration_minutes=r.get("duration_minutes"),
                    skills=r.get("skills") or [],
                    competency_headings=r.get("competency_headings") or [],
                    order=r.get("order"),
                )
                for r in payload.get("rounds", [])
            ],
        )

    def _build_triplets(self, packet: PlanPacket) -> list[Triplet]:
        triplets: list[Triplet] = []
        req = packet.requisition

        req_attrs = {
            "role_title": req.role_title,
            "status": req.status,
            "experience_min_years": req.experience_min_years,
            "experience_max_years": req.experience_max_years,
            "role_location": req.role_location,
        }

        if req.organization_name and req.organization_id:
            org_attrs = {
                "name": req.organization_name,
                "organization_ref": req.organization_id,
                "domain": req.organization_domain,
            }
            triplets.append(Triplet(
                source_name=req.organization_name,
                source_type="Organization",
                source_id=req.organization_id,
                source_attributes=org_attrs,
                target_name=req.role_title,
                target_type="Requisition",
                target_id=req.id,
                target_attributes=req_attrs,
                relation="HOSTS",
                edge_attributes={},
            ))

        for i, round_data in enumerate(packet.rounds):
            normalized_category = normalize_round_category(round_data.category)

            triplets.append(Triplet(
                source_name=req.role_title,
                source_type="Requisition",
                source_id=req.id,
                source_attributes=req_attrs,
                target_name=round_data.name,
                target_type="Round",
                target_id=round_data.id,
                target_attributes={"name": round_data.name, "category": normalized_category, "duration_minutes": round_data.duration_minutes},
                relation="HAS_ROUND",
                edge_attributes={"order": round_data.order if round_data.order is not None else i},
            ))

            for skill in round_data.skills:
                triplets.append(Triplet(
                    source_name=round_data.name,
                    source_type="Round",
                    source_id=round_data.id,
                    source_attributes={"name": round_data.name, "category": normalized_category},
                    target_name=skill,
                    target_type="Skill",
                    target_attributes={"name": skill},
                    relation="ASSESSES",
                    edge_attributes={},
                ))

            for heading in round_data.competency_headings:
                normalized_heading = normalize_competency(heading)
                triplets.append(Triplet(
                    source_name=round_data.name,
                    source_type="Round",
                    source_id=round_data.id,
                    source_attributes={"name": round_data.name, "category": normalized_category},
                    target_name=normalized_heading,
                    target_type="Competency",
                    target_attributes={"heading": normalized_heading},
                    relation="ASSESSES",
                    edge_attributes={},
                ))

        if req.role_location:
            location_type = "remote" if req.role_location.lower() in ("remote", "fully remote") else None
            triplets.append(Triplet(
                source_name=req.role_title,
                source_type="Requisition",
                source_id=req.id,
                source_attributes=req_attrs,
                target_name=req.role_location,
                target_type="Location",
                target_attributes={"name": req.role_location, "location_type": location_type},
                relation="LOCATED_IN",
                edge_attributes={},
            ))

        for skill in req.must_have_skills:
            triplets.append(Triplet(
                source_name=req.role_title,
                source_type="Requisition",
                source_id=req.id,
                source_attributes=req_attrs,
                target_name=skill,
                target_type="Skill",
                target_attributes={"name": skill},
                relation="REQUIRES",
                edge_attributes={},
            ))

        for skill in req.nice_to_have_skills:
            triplets.append(Triplet(
                source_name=req.role_title,
                source_type="Requisition",
                source_id=req.id,
                source_attributes=req_attrs,
                target_name=skill,
                target_type="Skill",
                target_attributes={"name": skill},
                relation="NICE_TO_HAVE",
                edge_attributes={},
            ))

        return triplets
