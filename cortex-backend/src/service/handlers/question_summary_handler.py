import structlog

from src.model.ingestion import SourceRef
from src.model.packets import EpisodicMetadata
from src.ontology.quality_filters import compute_trait_weight, filter_markets, filter_traits
from src.service.concept_extractor import ConceptExtractor
from src.service.graph_ingestion_service import Triplet, GraphIngestionService
from src.service.handlers.base_handler import BaseHandler
from src.service.supabase_fetcher import SupabaseFetcher

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = """You are an expert talent intelligence analyst. Extract concept entities from interview question summaries.

KNOWN ENTITIES (already in graph — do NOT create nodes for these):
- Candidate: {candidate_name} (ID: {candidate_id})
- Round: {round_name} ({round_category}) for "{role_title}"

CRITICAL CONTEXT — READ CAREFULLY:
This text is a third-party SUMMARY of how the CANDIDATE answered specific interview questions. It is descriptive narrative ABOUT THE CANDIDATE — not direct speech, not interviewer self-reflection.
Every observation in this text is about the CANDIDATE's behavior, claims, or demonstrated skills.

ATTRIBUTION RULES (CRITICAL — violations corrupt the graph):
- All extracted candidate_traits, skills, and markets describe THE CANDIDATE. Set "attributed_to": "candidate" on every trait.
- Do NOT extract interviewer_traits — set this list to empty. There is no interviewer subject in this text.
- If the summary describes the interviewer (e.g., "the interviewer probed deeply"), IGNORE — that signal does not belong in this extraction path.

NAMING RULES:
- Trait names: 1-6 words, noun-phrase form. Never a sentence. Never a single common word like "good".
- Market names: industries / domains / segments only. Never skills, traits, or capabilities.

Return a JSON object with these arrays (empty array if nothing found):
- "candidate_traits": [{{"name": str, "category": "communication"|"leadership"|"execution"|"strategic"|"interpersonal"|"cultural", "polarity": "positive"|"negative"|"neutral"|"contextual", "evidence": str, "confidence": "high"|"medium"|"low", "attributed_to": "candidate"}}]
- "skills": [{{"name": str, "evidence": str, "claim_type": "demonstrated"|"claimed"}}]
- "markets": [{{"name": str, "category": "industry"|"domain"|"segment"|"business_model", "depth": "deep"|"moderate"|"exposure"}}]
- "companies": []
- "interviewer_traits": []
- "career_history": []
- "locations": []

The "attributed_to" field is REQUIRED on every candidate_trait. Items with mismatched attribution will be rejected.
Extract behavioral patterns, work styles, skills demonstrated, and domain expertise.
Be specific — "systematic problem solver" is better than "good at problem solving"."""


class QuestionSummaryHandler(BaseHandler):
    def __init__(self, fetcher: SupabaseFetcher, ingestion_service: GraphIngestionService, concept_extractor: ConceptExtractor):
        super().__init__(fetcher, ingestion_service)
        self._extractor = concept_extractor

    async def fetch_and_build_triplets(self, source_ref: SourceRef, org_id: str) -> list[Triplet]:
        metadata = await self._fetcher.fetch_episodic_metadata(source_ref.candidate_round_id)
        self._validate_org(metadata.organization_id, org_id)

        qs = await self._fetcher.fetch_question_summaries(source_ref.candidate_round_id)
        if not qs:
            logger.info("no_question_summaries", candidate_round_id=source_ref.candidate_round_id)
            return []

        text = "\n\n".join(f"Question {k}: {v}" for k, v in sorted(qs.items()))

        prompt = SYSTEM_PROMPT.format(
            candidate_name=metadata.candidate_name,
            candidate_id=metadata.candidate_id,
            round_name=metadata.round_name,
            round_category=metadata.round_category or "generic",
            role_title=metadata.role_title,
        )

        concepts = await self._extractor.extract(text, prompt)
        if not concepts:
            return []
        return self._build_triplets(metadata, concepts)

    def build_triplets_from_payload(self, payload: dict, org_id: str) -> list[Triplet]:
        raise NotImplementedError("QuestionSummaryHandler does not support direct payload ingestion")

    def _build_triplets(self, metadata: EpisodicMetadata, concepts: dict) -> list[Triplet]:
        concepts = dict(concepts)
        concepts["candidate_traits"] = filter_traits(concepts.get("candidate_traits") or [], handler="question_summary")
        concepts["markets"] = filter_markets(concepts.get("markets") or [])
        triplets: list[Triplet] = []
        candidate_attrs = {"name": metadata.candidate_name, "candidate_ref": metadata.candidate_id}

        for trait in concepts.get("candidate_traits", []):
            attributed = (trait.get("attributed_to") or "").strip().lower()
            if attributed and attributed != "candidate":
                logger.warning(
                    "trait_attribution_mismatch_dropped",
                    handler="question_summary",
                    expected="candidate",
                    got=attributed,
                    name=trait.get("name"),
                )
                continue
            triplets.append(Triplet(
                source_name=metadata.candidate_name,
                source_type="Candidate",
                source_id=metadata.candidate_id,
                source_attributes=candidate_attrs,
                target_name=trait["name"],
                target_type="Trait",
                target_attributes={"name": trait["name"], "category": trait.get("category"), "polarity": trait.get("polarity")},
                relation="EXHIBITS",
                edge_attributes={
                    "evidence": trait.get("evidence"),
                    "source": "question_summary",
                    "confidence": trait.get("confidence"),
                    "weight": compute_trait_weight(trait.get("confidence"), "question_summary"),
                },
            ))

        for skill in concepts.get("skills", []):
            claim_type = skill.get("claim_type", "claimed")
            relation = "DEMONSTRATED" if claim_type == "demonstrated" else "CLAIMED"
            triplets.append(Triplet(
                source_name=metadata.candidate_name,
                source_type="Candidate",
                source_id=metadata.candidate_id,
                source_attributes=candidate_attrs,
                target_name=skill["name"],
                target_type="Skill",
                target_attributes={"name": skill["name"]},
                relation=relation,
                edge_attributes={"evidence": skill.get("evidence")},
            ))

        for market in concepts.get("markets", []):
            triplets.append(Triplet(
                source_name=metadata.candidate_name,
                source_type="Candidate",
                source_id=metadata.candidate_id,
                source_attributes=candidate_attrs,
                target_name=market["name"],
                target_type="Market",
                target_attributes={"name": market["name"], "category": market.get("category")},
                relation="EXPERIENCED_IN",
                edge_attributes={"depth": market.get("depth")},
            ))

        return triplets
