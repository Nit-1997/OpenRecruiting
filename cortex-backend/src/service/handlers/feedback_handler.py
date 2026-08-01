import structlog

from src.model.ingestion import SourceRef
from src.model.packets import FeedbackPacket, CandidateRoundData, RoundData, CandidateData, FeedbackItemData
from src.ontology.normalizers import normalize_round_category, normalize_competency
from src.service.graph_ingestion_service import Triplet
from src.service.handlers.base_handler import BaseHandler

logger = structlog.get_logger(__name__)

RATING_TO_EDGE: dict[str | None, str] = {
    "strong_yes": "STRONG_IN",
    "yes": "STRONG_IN",
    "no": "WEAK_IN",
    "strong_no": "WEAK_IN",
    "maybe": "ASSESSED_ON",
    None: "ASSESSED_ON",
}


class FeedbackHandler(BaseHandler):
    async def fetch_and_build_triplets(self, source_ref: SourceRef, org_id: str) -> list[Triplet]:
        packet = await self._fetcher.fetch_feedback_packet(source_ref.candidate_round_id)
        self._validate_org(packet.requisition.organization_id, org_id)
        return self._build_triplets(packet)

    def build_triplets_from_payload(self, payload: dict, org_id: str) -> list[Triplet]:
        packet = self._parse_packet(payload)
        return self._build_triplets(packet)

    def _parse_packet(self, payload: dict) -> FeedbackPacket:
        cr = payload["candidate_round"]
        return FeedbackPacket(
            candidate_round=CandidateRoundData(**cr),
            round=RoundData(**payload["round"]),
            requisition=_skip_parse("requisition", payload),
            candidate=CandidateData(**payload["candidate"]),
            feedback_items=[FeedbackItemData(**fi) for fi in payload.get("feedback_items", [])],
        )

    def _build_triplets(self, packet: FeedbackPacket) -> list[Triplet]:
        triplets: list[Triplet] = []
        cr = packet.candidate_round
        candidate = packet.candidate
        round_data = packet.round

        normalized_category = normalize_round_category(round_data.category)

        triplets.append(Triplet(
            source_name=candidate.name,
            source_type="Candidate",
            source_id=candidate.id,
            source_attributes={"name": candidate.name, "candidate_ref": candidate.id, "status": candidate.status},
            target_name=round_data.name,
            target_type="Round",
            target_id=round_data.id,
            target_attributes={"name": round_data.name, "category": normalized_category, "duration_minutes": round_data.duration_minutes},
            relation="INTERVIEWED_IN",
            edge_attributes={"rating": cr.rating},
        ))

        round_rating = cr.rating
        round_edge_type = RATING_TO_EDGE.get(round_rating, "ASSESSED_ON")
        # Skip competency edges entirely if no rating AND no per-question evidence — pipeline candidate, no signal yet.
        if round_rating is None and not any(item.feedback_text or item.evidence for item in packet.feedback_items):
            packet.feedback_items = []
        for item in packet.feedback_items:
            normalized_heading = normalize_competency(item.heading)
            has_per_item_evidence = bool(item.feedback_text or item.evidence)
            edge_type = round_edge_type if not has_per_item_evidence else (
                round_edge_type if item.evidence_status == "supported" else "ASSESSED_ON"
            )
            edge_attrs = {
                "evidence_status": item.evidence_status if item.evidence_status in {"supported", "unsupported"} else (
                    "per_item" if has_per_item_evidence else "from_rating"
                ),
                "feedback_text": item.feedback_text,
                "evidence": item.evidence or None,
                "round_rating": round_rating,
            }
            triplets.append(Triplet(
                source_name=candidate.name,
                source_type="Candidate",
                source_id=candidate.id,
                source_attributes={"name": candidate.name, "candidate_ref": candidate.id},
                target_name=normalized_heading,
                target_type="Competency",
                target_attributes={"heading": normalized_heading},
                relation=edge_type,
                edge_attributes=edge_attrs,
            ))

        if cr.interviewer_email:
            interviewer_display = cr.interviewer_name or cr.interviewer_email
            triplets.append(Triplet(
                source_name=interviewer_display,
                source_type="Interviewer",
                source_id=cr.interviewer_email,
                source_attributes={"interviewer_ref": cr.interviewer_email},
                target_name=round_data.name,
                target_type="Round",
                target_id=round_data.id,
                target_attributes={"name": round_data.name, "category": normalized_category},
                relation="CONDUCTED",
                edge_attributes={},
            ))

        return triplets


def _skip_parse(key: str, payload: dict):
    from src.model.packets import RequisitionData
    data = payload[key]
    return RequisitionData(
        id=data["id"],
        role_title=data["role_title"],
        organization_id=data.get("organization_id", ""),
        status=data.get("status"),
        experience_min_years=data.get("experience_min_years"),
        experience_max_years=data.get("experience_max_years"),
        role_location=data.get("role_location"),
        must_have_skills=data.get("must_have_skills") or [],
        nice_to_have_skills=data.get("nice_to_have_skills") or [],
    )
