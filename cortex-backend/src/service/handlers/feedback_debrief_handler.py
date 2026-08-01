import structlog

from src.model.ingestion import SourceRef
from src.model.packets import EpisodicMetadata
from src.ontology.quality_filters import (
    compute_demonstrates_weight,
    compute_trait_weight,
    filter_traits,
)
from src.service.concept_extractor import ConceptExtractor
from src.service.graph_ingestion_service import Triplet, GraphIngestionService
from src.service.handlers.base_handler import BaseHandler
from src.service.supabase_fetcher import SupabaseFetcher

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = """You are an expert talent intelligence analyst. Extract concept entities from post-interview feedback where an interviewer verbally assesses a candidate.

KNOWN ENTITIES (already in graph — do NOT create nodes for these):
- Candidate: {candidate_name} (ID: {candidate_id})
- Interviewer ref: {interviewer_ref}
- Round: {round_name} ({round_category}) for "{role_title}"

CRITICAL CONTEXT — READ CAREFULLY:
This text is a POST-INTERVIEW FEEDBACK MONOLOGUE spoken entirely by the INTERVIEWER about the CANDIDATE.
The candidate is NOT speaking. Every word came from the interviewer. The candidate is the SUBJECT being evaluated, never the speaker.

ATTRIBUTION RULES (CRITICAL — violations corrupt the graph):
- candidate_traits = qualities the interviewer OBSERVES ABOUT THE CANDIDATE (subject = candidate).
  The interviewer is the speaker, but the candidate is the subject. Set "attributed_to": "candidate".
  Example: "She struggled with edge cases" → candidate_trait, name="struggles with edge cases", attributed_to="candidate".
  Example: "He showed strong product ownership" → candidate_trait, attributed_to="candidate".
  The OVERWHELMING MAJORITY of traits in this monologue are candidate_traits.
- interviewer_traits = qualities about the INTERVIEWER (subject = interviewer).
  ONLY extract these when the interviewer EXPLICITLY reflects on their OWN evaluation process, style, mental model, or values.
  Set "attributed_to": "interviewer". Use SPARINGLY.
  Valid examples:
    "I'm uncertain — maybe it should be a maybe" → interviewer_trait (uncertain assessor), attributed_to="interviewer"
    "I always look for evidence of customer empathy" → interviewer_trait (customer-empathy gate), attributed_to="interviewer"
    "I'll defer to the next round" → interviewer_trait (defers decisions), attributed_to="interviewer"
  INVALID — these are candidate_traits, NOT interviewer_traits:
    "He was authentic" — subject is candidate, not interviewer.
    "Communication was alright" — assessing the candidate, not describing self.
    "Concerns about rollout" — concerns ABOUT the candidate's rollout thinking → candidate_trait (weak rollout thinking).

When in doubt, classify as candidate_trait or skip entirely. NEVER turn an evaluation of the candidate into an interviewer_trait.

NAMING RULES (trait "name" field):
- 1-6 words, noun-phrase form ("verbose communicator", "outcome-focused", "lacks global maturity").
- NEVER a sentence — move full descriptions into "evidence".
- NEVER a generic single word ("good", "bad", "smart", "amazing").
- Example BAD: "She was good", "decent understanding of past projects and decision making".
- Example GOOD: "decent project understanding", "concise communicator".

Return a JSON object with these arrays (empty array if nothing found):
- "candidate_traits": [{{"name": str, "category": "communication"|"leadership"|"execution"|"strategic"|"interpersonal"|"cultural", "polarity": "positive"|"negative"|"neutral"|"contextual", "evidence": str, "confidence": "high"|"medium"|"low", "attributed_to": "candidate"}}]
- "interviewer_traits": [{{"name": str, "category": "communication"|"leadership"|"execution"|"strategic"|"interpersonal"|"cultural", "polarity": "positive"|"negative"|"neutral"|"contextual", "evidence": str, "pattern_frequency": "consistent"|"occasional"|"one_time", "attributed_to": "interviewer"}}]
- "gaps": [{{"domain": str, "evidence": str, "depth": "deep"|"moderate"|"exposure"}}]

The "attributed_to" field is REQUIRED on every trait. Items with mismatched attribution will be rejected.
Focus on behavioral patterns, interviewer confidence/certainty, and domain/market gaps."""


class FeedbackDebriefHandler(BaseHandler):
    def __init__(self, fetcher: SupabaseFetcher, ingestion_service: GraphIngestionService, concept_extractor: ConceptExtractor):
        super().__init__(fetcher, ingestion_service)
        self._extractor = concept_extractor

    async def fetch_and_build_triplets(self, source_ref: SourceRef, org_id: str) -> list[Triplet]:
        metadata = await self._fetcher.fetch_episodic_metadata(source_ref.candidate_round_id)
        self._validate_org(metadata.organization_id, org_id)

        text = await self._fetcher.fetch_feedback_transcript(source_ref.candidate_round_id)
        if not text:
            logger.info("no_feedback_transcript", candidate_round_id=source_ref.candidate_round_id)
            return []

        prompt = SYSTEM_PROMPT.format(
            candidate_name=metadata.candidate_name,
            candidate_id=metadata.candidate_id,
            interviewer_ref=metadata.interviewer_name or metadata.interviewer_ref or "unknown",
            round_name=metadata.round_name,
            round_category=metadata.round_category or "generic",
            role_title=metadata.role_title,
        )

        concepts = await self._extractor.extract(text, prompt)
        if not concepts:
            return []
        return self._build_triplets(metadata, concepts)

    def build_triplets_from_payload(self, payload: dict, org_id: str) -> list[Triplet]:
        raise NotImplementedError("FeedbackDebriefHandler does not support direct payload ingestion")

    def _build_triplets(self, metadata: EpisodicMetadata, concepts: dict) -> list[Triplet]:
        from src.ontology.quality_filters import is_valid_market
        concepts = dict(concepts)
        concepts["candidate_traits"] = filter_traits(concepts.get("candidate_traits") or [], handler="feedback_debrief")
        concepts["interviewer_traits"] = filter_traits(concepts.get("interviewer_traits") or [], handler="feedback_debrief")
        # gaps emit a Market node — apply same purity filter as direct markets
        kept_gaps = []
        for gap in concepts.get("gaps") or []:
            if is_valid_market((gap or {}).get("domain") or ""):
                kept_gaps.append(gap)
            else:
                logger.warning("gap_domain_dropped_invalid", domain=(gap or {}).get("domain"))
        concepts["gaps"] = kept_gaps
        triplets: list[Triplet] = []
        candidate_attrs = {"name": metadata.candidate_name, "candidate_ref": metadata.candidate_id}

        for trait in concepts.get("candidate_traits", []):
            if not _attributed_to(trait, "candidate"):
                logger.warning(
                    "trait_attribution_mismatch_dropped",
                    handler="feedback_debrief",
                    expected="candidate",
                    got=trait.get("attributed_to"),
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
                    "source": "feedback",
                    "confidence": trait.get("confidence"),
                    "weight": compute_trait_weight(trait.get("confidence"), "feedback"),
                },
            ))

        if metadata.interviewer_ref is not None:
            interviewer_display = metadata.interviewer_name or metadata.interviewer_ref
            interviewer_attrs = {"interviewer_ref": metadata.interviewer_ref}
            for trait in concepts.get("interviewer_traits", []):
                if not _attributed_to(trait, "interviewer"):
                    logger.warning(
                        "trait_attribution_mismatch_dropped",
                        handler="feedback_debrief",
                        expected="interviewer",
                        got=trait.get("attributed_to"),
                        name=trait.get("name"),
                    )
                    continue
                triplets.append(Triplet(
                    source_name=interviewer_display,
                    source_type="Interviewer",
                    source_id=metadata.interviewer_ref,
                    source_attributes=interviewer_attrs,
                    target_name=trait["name"],
                    target_type="Trait",
                    target_attributes={"name": trait["name"], "category": trait.get("category")},
                    relation="DEMONSTRATES",
                    edge_attributes={
                        "evidence": trait.get("evidence"),
                        "pattern_frequency": trait.get("pattern_frequency"),
                        "weight": compute_demonstrates_weight(trait.get("pattern_frequency")),
                    },
                ))

        for gap in concepts.get("gaps", []):
            triplets.append(Triplet(
                source_name=metadata.candidate_name,
                source_type="Candidate",
                source_id=metadata.candidate_id,
                source_attributes=candidate_attrs,
                target_name=gap["domain"],
                target_type="Market",
                target_attributes={"name": gap["domain"]},
                relation="EXPERIENCED_IN",
                edge_attributes={"depth": gap.get("depth"), "evidence": gap.get("evidence")},
            ))

        return triplets


def _attributed_to(trait: dict, expected: str) -> bool:
    value = (trait.get("attributed_to") or "").strip().lower()
    return value == expected
