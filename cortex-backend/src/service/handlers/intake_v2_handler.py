"""IntakeV2Handler — consume `intake_v2_completed` SQS events from intake-agent-v2.

Builds the full set of triplets per spec §4.6 and (in handle()) writes a raw
transcript episode to Cortex for semantic search.

Does NOT extend or modify the v1 IntakeHandler. v1 is retired in Phase 7.
"""
from __future__ import annotations

import re
from typing import Any

import structlog

from src.model.ingestion import SourceRef
from src.model.packets import IntakeV2Packet
from src.service.graph_ingestion_service import GraphIngestionService, IngestionResult, Triplet
from src.service.handlers.base_handler import BaseHandler
from src.service.supabase_fetcher import SupabaseFetcher
from src.sync.provenance import Provenance

logger = structlog.get_logger(__name__)


_SPLIT_RE = re.compile(r"[,;\n]|(?:\s+and\s+)")


def _split_csv_phrase(raw: str) -> list[str]:
    """Split "Python, PostgreSQL, REST at scale" -> ["Python", "PostgreSQL", "REST at scale"]."""
    if not raw:
        return []
    return [s.strip() for s in _SPLIT_RE.split(raw) if s.strip()]


class IntakeV2Handler(BaseHandler):
    """Handler for the `intake_v2_completed` event.

    Reads from intake_sessions + interview_plan; creates 9 relation types in spec §4.6
    plus an episodic memory of the full transcript.
    """

    def __init__(
        self,
        fetcher: SupabaseFetcher,
        ingestion_service: GraphIngestionService,
    ):
        super().__init__(fetcher, ingestion_service)

    async def fetch_and_build_triplets(self, source_ref: SourceRef, org_id: str) -> list[Triplet]:
        session_id = getattr(source_ref, "session_id", None) or getattr(source_ref, "requisition_id", None)
        if not session_id:
            logger.warning("intake_v2_missing_session_id", source_ref=str(source_ref))
            return []

        packet = await self._fetcher.fetch_intake_v2_session(session_id)
        self._validate_org(packet.organization_id, org_id)
        return self._build_triplets(packet)

    def build_triplets_from_payload(self, payload: dict, org_id: str) -> list[Triplet]:
        raise NotImplementedError("IntakeV2Handler does not support direct payload ingestion")

    def _build_triplets(self, packet: IntakeV2Packet) -> list[Triplet]:
        triplets: list[Triplet] = []
        req_attrs = {
            "role_title": packet.role_title,
            "role_location": packet.role_location,
            "experience_min_years": packet.experience_min_years,
            "experience_max_years": packet.experience_max_years,
            "requisition_ref": packet.requisition_id,
        }
        req_source = {
            "source_name": packet.role_title,
            "source_type": "Requisition",
            "source_id": packet.requisition_id,
            "source_attributes": req_attrs,
        }

        # 1) Org -[HOSTS]-> Requisition
        triplets.append(Triplet(
            source_name=packet.organization_id,
            source_type="Org",
            source_id=packet.organization_id,
            source_attributes={"organization_id": packet.organization_id},
            target_name=packet.role_title,
            target_type="Requisition",
            target_id=packet.requisition_id,
            target_attributes=req_attrs,
            relation="HOSTS",
            edge_attributes={"source": "intake_v2"},
        ))

        # 2) Requisition -[TARGETS]-> Market
        q1 = (packet.current_answers.get("q1_role_overview") or {}).get("text") or ""
        for market_name in self._extract_markets(q1, packet.role_title):
            triplets.append(Triplet(
                **req_source,
                target_name=market_name,
                target_type="Market",
                target_attributes={"name": market_name},
                relation="TARGETS",
                edge_attributes={"source": "intake_v2"},
            ))

        # 3) Requisition -[LOCATED_IN]-> Location
        if packet.role_location:
            triplets.append(Triplet(
                **req_source,
                target_name=packet.role_location,
                target_type="Location",
                target_attributes={"name": packet.role_location},
                relation="LOCATED_IN",
                edge_attributes={"source": "intake_v2"},
            ))

        # 4) Requisition -[REQUIRES]-> Skill (from q4_must_haves)
        q4 = (packet.current_answers.get("q4_must_haves") or {}).get("text") or ""
        for skill in _split_csv_phrase(q4):
            triplets.append(Triplet(
                **req_source,
                target_name=skill,
                target_type="Skill",
                target_attributes={"name": skill},
                relation="REQUIRES",
                edge_attributes={"priority": "must_have", "source": "intake_v2"},
            ))

        # 5) Requisition -[NICE_TO_HAVE]-> Skill (from q5_nice_to_haves)
        q5 = (packet.current_answers.get("q5_nice_to_haves") or {}).get("text") or ""
        for skill in _split_csv_phrase(q5):
            triplets.append(Triplet(
                **req_source,
                target_name=skill,
                target_type="Skill",
                target_attributes={"name": skill},
                relation="NICE_TO_HAVE",
                edge_attributes={"priority": "nice_to_have", "source": "intake_v2"},
            ))

        # 6) Requisition -[VALUES]-> Trait (from q6_cultural_fit)
        q6 = (packet.current_answers.get("q6_cultural_fit") or {}).get("text") or ""
        for trait in _split_csv_phrase(q6):
            triplets.append(Triplet(
                **req_source,
                target_name=trait,
                target_type="Trait",
                target_attributes={"name": trait, "category": "cultural"},
                relation="VALUES",
                edge_attributes={"priority": "implicit", "source": "intake_v2"},
            ))

        # 7) Requisition -[HAS_ROUND]-> Round AND
        # 8) Round -[ASSESSES]-> Competency (from feedback_questions)
        for r_idx, r in enumerate(packet.rounds):
            round_name = r.get("name") or f"Round {r_idx + 1}"
            round_id = r.get("round_id") or f"{packet.requisition_id}:round:{r_idx}"
            round_attrs = {
                "name": round_name,
                "category": r.get("category"),
                "order_index": r_idx,
            }
            triplets.append(Triplet(
                **req_source,
                target_name=round_name,
                target_type="Round",
                target_id=round_id,
                target_attributes=round_attrs,
                relation="HAS_ROUND",
                edge_attributes={"order_index": r_idx, "source": "intake_v2"},
            ))
            for fq in r.get("feedback_questions") or []:
                comp_name = fq.get("heading") or "General Assessment"
                triplets.append(Triplet(
                    source_name=round_name,
                    source_type="Round",
                    source_id=round_id,
                    source_attributes=round_attrs,
                    target_name=comp_name,
                    target_type="Competency",
                    target_attributes={"name": comp_name, "description": fq.get("description")},
                    relation="ASSESSES",
                    edge_attributes={"source": "intake_v2"},
                ))

        logger.info(
            "intake_v2_triplets_built",
            session_id=packet.session_id,
            requisition_id=packet.requisition_id,
            triplet_count=len(triplets),
            relation_counts={r: sum(1 for t in triplets if t.relation == r)
                             for r in {t.relation for t in triplets}},
        )
        return triplets

    def _extract_markets(self, q1_text: str, role_title: str) -> list[str]:
        """Cheap market extraction from q1 + role_title text."""
        text = f"{role_title} {q1_text}".lower()
        markets: list[str] = []
        for keyword, market_name in [
            ("payments", "Payments"),
            ("fintech", "Fintech"),
            ("healthcare", "Healthcare"),
            ("ml", "Machine Learning"),
            ("infrastructure", "Infrastructure"),
            ("platform", "Platform Engineering"),
        ]:
            if keyword in text:
                markets.append(market_name)
        return markets

    async def handle(
        self,
        source_ref: SourceRef,
        org_id: str,
        provenance: Provenance | None = None,
    ) -> IngestionResult:
        """Override BaseHandler.handle to also write a raw transcript episode."""
        triplets = await self.fetch_and_build_triplets(source_ref, org_id)
        result = await self._ingestion_service.ingest_triplets(
            triplets, org_id, provenance=provenance
        )

        # Episode write — best-effort, doesn't fail the handler if it errors
        try:
            session_id = getattr(source_ref, "session_id", None) or getattr(source_ref, "requisition_id", None)
            if session_id:
                packet = await self._fetcher.fetch_intake_v2_session(session_id)
                await self._add_episode(packet, org_id)
        except Exception as ep_err:
            logger.warning("intake_v2_episode_failed", error=str(ep_err))
            result.errors.append(f"episode write failed: {str(ep_err)[:200]}")

        return result

    async def _add_episode(self, packet: IntakeV2Packet, org_id: str) -> None:
        """Write raw conversation transcript as a Graphiti episode."""
        content = _format_transcript_for_episode(packet.turns)
        if not content.strip():
            logger.info("intake_v2_episode_skipped_empty", session_id=packet.session_id)
            return

        from datetime import datetime, timezone
        try:
            from graphiti_core.nodes import EpisodeType
            episode_type = EpisodeType.message
        except Exception:
            episode_type = None

        await self._ingestion_service._graphiti.add_episode(
            name=f"intake_v2:{packet.session_id}",
            episode_body=content,
            source_description=(
                f"v2 intake session for requisition {packet.requisition_id} "
                f"(role: {packet.role_title}); modalities: {','.join(packet.modalities_used or [])}; "
                f"questions_version: {packet.questions_version}"
            ),
            reference_time=datetime.now(timezone.utc),
            group_id=org_id,
            **({"source": episode_type} if episode_type is not None else {}),
        )
        logger.info(
            "intake_v2_episode_added",
            session_id=packet.session_id,
            requisition_id=packet.requisition_id,
            content_length=len(content),
        )


def _format_transcript_for_episode(turns: list[dict[str, Any]]) -> str:
    """Format turns[] into a readable transcript per spec §4.6."""
    lines: list[str] = []
    for t in turns:
        modality = t.get("modality") or "voice"
        role = t.get("role") or "user"
        content = (t.get("content") or "").strip()
        if not content:
            continue
        speaker = "Recruiter" if role == "user" else "Scout"
        lines.append(f"[{modality.capitalize()}] {speaker}: {content}")
    return "\n".join(lines)
