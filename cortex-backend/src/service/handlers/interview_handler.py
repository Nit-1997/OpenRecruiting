import structlog

from src.model.ingestion import SourceRef
from src.model.packets import EpisodicMetadata
from src.ontology.quality_filters import (
    compute_demonstrates_weight,
    compute_trait_weight,
    filter_markets,
    filter_traits,
)
from src.service.concept_extractor import ConceptExtractor
from src.service.graph_ingestion_service import Triplet, GraphIngestionService
from src.service.handlers.base_handler import BaseHandler
from src.service.supabase_fetcher import SupabaseFetcher
from src.service.transcript_reconstructor import reconstruct_with_roles

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = """You are an expert talent intelligence analyst. Extract concept entities from an interview transcript.

KNOWN ENTITIES (already in graph — do NOT create nodes for these):
- Candidate: {candidate_name} (ID: {candidate_id})
- Interviewer: {interviewer_ref}
- Round: {round_name} ({round_category}) for "{role_title}"

TRANSCRIPT FORMAT:
Each line is prefixed with a role tag — [CANDIDATE], [INTERVIEWER], or [OTHER] — followed by the speaker name and their utterance.
The role tag is the GROUND TRUTH for who is speaking. Use it to attribute every extracted concept correctly.

ATTRIBUTION RULES (CRITICAL — violations corrupt the graph):
- candidate_traits = qualities OBSERVED ABOUT THE CANDIDATE (subject = candidate). Sources:
  • [CANDIDATE] turns where the candidate self-describes ("I always prioritize outcomes")
  • [INTERVIEWER] turns where the interviewer evaluates the candidate ("you struggled with concision")
  In both cases the SUBJECT is the candidate; set "attributed_to": "candidate".
- interviewer_traits = qualities OBSERVED ABOUT THE INTERVIEWER (subject = interviewer). Sources:
  • [INTERVIEWER] turns where the interviewer reveals their OWN style/process/values
    ("I always probe for edge cases", "I like to push back on assumptions")
  • Behavioral patterns inferred from how the interviewer questions across multiple turns
  Set "attributed_to": "interviewer".
- NEVER turn an interviewer's evaluation of the candidate into an interviewer_trait. If the [INTERVIEWER] is talking ABOUT the candidate, the trait belongs in candidate_traits.
- NEVER attribute to the candidate something stated by the interviewer about themselves.
- For skills/career/companies/markets — these always describe the candidate's work history. Extract only from [CANDIDATE] self-descriptions or unambiguous [INTERVIEWER] confirmations.

NAMING RULES (extracted name fields):
- Trait names: 1-6 words, noun-phrase form ("outcome-focused", "verbose communicator", "limited global exposure"). Never a full sentence. Never a single common word like "good", "bad", "smart". Move long descriptions into "evidence", not "name".
- Market names: industries, business segments, or domains ("Fintech", "B2B SaaS", "AI Infrastructure", "EdTech"). NEVER a skill, trait, or capability. Reject "Communication Skills", "technical knowledge", "strategic thinking" — those go into traits/skills.

Return a JSON object with these arrays (empty array if nothing found):
- "career_history": [{{"company_name": str, "role_title": str, "duration": str, "what_they_built": str, "achievement": str, "seniority_signal": str}}]
- "companies": [{{"name": str, "size_signal": "startup"|"scaleup"|"enterprise"|"unknown", "domain_summary": str}}]
- "company_markets": [{{"company": str, "market": str, "role": "primary"|"secondary"|"expanding_into"}}]
- "markets": [{{"name": str, "category": "industry"|"domain"|"segment"|"business_model", "depth": "deep"|"moderate"|"exposure", "geographic_scope": str}}]
- "skills": [{{"name": str, "evidence": str, "claim_type": "demonstrated"|"claimed"}}]
- "candidate_traits": [{{"name": str, "category": "communication"|"leadership"|"execution"|"strategic"|"interpersonal"|"cultural", "polarity": "positive"|"negative"|"neutral"|"contextual", "evidence": str, "confidence": "high"|"medium"|"low", "attributed_to": "candidate"}}]
- "interviewer_traits": [{{"name": str, "category": "communication"|"leadership"|"execution"|"strategic"|"interpersonal"|"cultural", "polarity": "positive"|"negative"|"neutral"|"contextual", "evidence": str, "pattern_frequency": "consistent"|"occasional"|"one_time", "attributed_to": "interviewer"}}]
- "locations": [{{"name": str, "location_type": "city"|"region"|"country"|"remote"}}]

The "attributed_to" field is REQUIRED on every trait. Items with mismatched attribution will be rejected.
Deduplicate: if a company appears 15 times, list it once. Extract the richest signal per entity.
For company_markets, explicitly state which company operates in which market."""


class InterviewHandler(BaseHandler):
    def __init__(self, fetcher: SupabaseFetcher, ingestion_service: GraphIngestionService, concept_extractor: ConceptExtractor):
        super().__init__(fetcher, ingestion_service)
        self._extractor = concept_extractor

    async def fetch_and_build_triplets(self, source_ref: SourceRef, org_id: str) -> list[Triplet]:
        metadata = await self._fetcher.fetch_episodic_metadata(source_ref.candidate_round_id)
        self._validate_org(metadata.organization_id, org_id)

        segments = await self._fetcher.fetch_interview_segments(source_ref.candidate_round_id)
        if not segments:
            logger.info("no_interview_segments", candidate_round_id=source_ref.candidate_round_id)
            return []

        text = reconstruct_with_roles(
            segments,
            candidate_name=metadata.candidate_name,
            interviewer_name=metadata.interviewer_name or metadata.interviewer_ref,
        )
        if not text.strip():
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
        raise NotImplementedError("InterviewHandler does not support direct payload ingestion")

    def _build_triplets(self, metadata: EpisodicMetadata, concepts: dict) -> list[Triplet]:
        concepts = dict(concepts)
        concepts["candidate_traits"] = filter_traits(concepts.get("candidate_traits") or [], handler="interview")
        concepts["interviewer_traits"] = filter_traits(concepts.get("interviewer_traits") or [], handler="interview")
        concepts["markets"] = filter_markets(concepts.get("markets") or [])
        triplets: list[Triplet] = []
        candidate_attrs = {"name": metadata.candidate_name, "candidate_ref": metadata.candidate_id}
        companies_by_name = {c["name"]: c for c in concepts.get("companies", [])}

        for entry in concepts.get("career_history", []):
            company_name = entry["company_name"]
            company_data = companies_by_name.get(company_name, {})
            triplets.append(Triplet(
                source_name=metadata.candidate_name,
                source_type="Candidate",
                source_id=metadata.candidate_id,
                source_attributes=candidate_attrs,
                target_name=company_name,
                target_type="Company",
                target_attributes={
                    "name": company_name,
                    "size_signal": company_data.get("size_signal"),
                    "domain_summary": company_data.get("domain_summary"),
                },
                relation="WORKED_AT",
                edge_attributes={
                    "role_title": entry.get("role_title"),
                    "duration": entry.get("duration"),
                    "what_they_built": entry.get("what_they_built"),
                    "achievement": entry.get("achievement"),
                    "seniority_signal": entry.get("seniority_signal"),
                },
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
                edge_attributes={
                    "depth": market.get("depth"),
                    "evidence": None,
                    "geographic_scope": market.get("geographic_scope"),
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

        for trait in concepts.get("candidate_traits", []):
            if not _attributed_to(trait, "candidate"):
                logger.warning(
                    "trait_attribution_mismatch_dropped",
                    handler="interview",
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
                    "source": "interview",
                    "confidence": trait.get("confidence"),
                    "weight": compute_trait_weight(trait.get("confidence"), "interview"),
                },
            ))

        if metadata.interviewer_ref is not None:
            interviewer_display = metadata.interviewer_name or metadata.interviewer_ref
            interviewer_attrs = {"interviewer_ref": metadata.interviewer_ref}
            for trait in concepts.get("interviewer_traits", []):
                if not _attributed_to(trait, "interviewer"):
                    logger.warning(
                        "trait_attribution_mismatch_dropped",
                        handler="interview",
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

        for loc in concepts.get("locations", []):
            triplets.append(Triplet(
                source_name=metadata.candidate_name,
                source_type="Candidate",
                source_id=metadata.candidate_id,
                source_attributes=candidate_attrs,
                target_name=loc["name"],
                target_type="Location",
                target_attributes={"name": loc["name"]},
                relation="BASED_IN",
                edge_attributes={},
            ))

        for cm in concepts.get("company_markets", []):
            co_attrs = companies_by_name.get(cm["company"], {"name": cm["company"]})
            triplets.append(Triplet(
                source_name=cm["company"],
                source_type="Company",
                source_attributes=co_attrs,
                target_name=cm["market"],
                target_type="Market",
                target_attributes={"name": cm["market"]},
                relation="OPERATES_IN",
                edge_attributes={"role": cm.get("role")},
            ))

        return triplets


def _attributed_to(trait: dict, expected: str) -> bool:
    value = (trait.get("attributed_to") or "").strip().lower()
    return value == expected
