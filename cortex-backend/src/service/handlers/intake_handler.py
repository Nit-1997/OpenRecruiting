import structlog

from src.model.ingestion import SourceRef
from src.model.packets import IntakeMetadata
from src.ontology.quality_filters import filter_markets, filter_traits, normalize_priority
from src.service.concept_extractor import ConceptExtractor
from src.service.graph_ingestion_service import Triplet, GraphIngestionService
from src.service.handlers.base_handler import BaseHandler
from src.service.supabase_fetcher import SupabaseFetcher

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = """You are an expert talent intelligence analyst. Extract concept entities from a recruitment intake call or research document.

The requisition is: {role_title} (ID: {requisition_id}).

Do NOT extract Candidate, Interviewer, Round, or Requisition entities — these are already known.

NAMING RULES:
- Skills: 1-4 words, noun-phrase. No sentences.
- Trait names: 1-6 words, noun-phrase ("strong product ownership", "outcome-focused"). No sentences. No generic words ("good", "bad").
- Market names: industries/domains/segments ONLY. NEVER traits/skills/capabilities. Reject "Communication Skills", "technical knowledge", "strategic thinking".

Return a JSON object with these arrays (empty array if nothing found):
- "companies": [{{"name": str, "size_signal": "startup"|"scaleup"|"enterprise"|"unknown", "domain_summary": str}}]
- "markets": [{{"name": str, "category": "industry"|"domain"|"segment"|"business_model"}}]
- "requisition_traits": [{{"name": str, "category": "communication"|"leadership"|"execution"|"strategic"|"interpersonal"|"cultural", "priority": "must_have"|"nice_to_have"|"implicit", "evidence": str}}]
- "company_traits": [{{"company": str, "name": str, "category": "communication"|"leadership"|"execution"|"strategic"|"interpersonal"|"cultural", "evidence": str}}]
- "company_markets": [{{"company": str, "market": str, "role": "primary"|"secondary"|"expanding_into"}}]
- "company_skills": [{{"company": str, "skill": str}}]
- "company_locations": [{{"company": str, "location": str}}]
- "skills": [{{"name": str, "evidence": str}}]"""


class IntakeHandler(BaseHandler):
    def __init__(self, fetcher: SupabaseFetcher, ingestion_service: GraphIngestionService, concept_extractor: ConceptExtractor):
        super().__init__(fetcher, ingestion_service)
        self._extractor = concept_extractor

    async def fetch_and_build_triplets(self, source_ref: SourceRef, org_id: str) -> list[Triplet]:
        metadata = await self._fetcher.fetch_intake_metadata(source_ref.requisition_id)
        self._validate_org(metadata.organization_id, org_id)

        text = await self._fetcher.fetch_intake_transcript(source_ref.requisition_id)
        if not text:
            logger.info("no_intake_transcript", requisition_id=source_ref.requisition_id)
            return []

        prompt = SYSTEM_PROMPT.format(
            role_title=metadata.role_title,
            requisition_id=metadata.requisition_id,
        )

        concepts = await self._extractor.extract(text, prompt)
        if not concepts:
            return []
        return self._build_triplets(metadata, concepts)

    def build_triplets_from_payload(self, payload: dict, org_id: str) -> list[Triplet]:
        raise NotImplementedError("IntakeHandler does not support direct payload ingestion")

    def _build_triplets(self, metadata: IntakeMetadata, concepts: dict) -> list[Triplet]:
        concepts = dict(concepts)
        concepts["markets"] = filter_markets(concepts.get("markets") or [])
        concepts["requisition_traits"] = filter_traits(concepts.get("requisition_traits") or [], handler="intake")
        triplets: list[Triplet] = []
        req_attrs = {"role_title": metadata.role_title, "requisition_ref": metadata.requisition_id}

        companies_by_name = {c["name"]: c for c in concepts.get("companies", [])}

        for market in concepts.get("markets", []):
            triplets.append(Triplet(
                source_name=metadata.role_title,
                source_type="Requisition",
                source_id=metadata.requisition_id,
                source_attributes=req_attrs,
                target_name=market["name"],
                target_type="Market",
                target_attributes={"name": market["name"], "category": market.get("category")},
                relation="TARGETS",
                edge_attributes={},
            ))

        for trait in concepts.get("requisition_traits", []):
            triplets.append(Triplet(
                source_name=metadata.role_title,
                source_type="Requisition",
                source_id=metadata.requisition_id,
                source_attributes=req_attrs,
                target_name=trait["name"],
                target_type="Trait",
                target_attributes={"name": trait["name"], "category": trait.get("category")},
                relation="VALUES",
                edge_attributes={"priority": normalize_priority(trait.get("priority")), "evidence": trait.get("evidence")},
            ))

        for ct in concepts.get("company_traits", []):
            company_name = ct["company"]
            company_data = companies_by_name.get(company_name, {})
            triplets.append(Triplet(
                source_name=company_name,
                source_type="Company",
                source_attributes={"name": company_name, "size_signal": company_data.get("size_signal"), "domain_summary": company_data.get("domain_summary")},
                target_name=ct["name"],
                target_type="Trait",
                target_attributes={"name": ct["name"], "category": ct.get("category")},
                relation="HAS_CULTURE",
                edge_attributes={"evidence": ct.get("evidence"), "source": "intake"},
            ))

        for cm in concepts.get("company_markets", []):
            company_name = cm["company"]
            company_data = companies_by_name.get(company_name, {})
            triplets.append(Triplet(
                source_name=company_name,
                source_type="Company",
                source_attributes={"name": company_name, "size_signal": company_data.get("size_signal"), "domain_summary": company_data.get("domain_summary")},
                target_name=cm["market"],
                target_type="Market",
                target_attributes={"name": cm["market"]},
                relation="OPERATES_IN",
                edge_attributes={"role": cm.get("role")},
            ))

        for cs in concepts.get("company_skills", []):
            company_name = cs["company"]
            company_data = companies_by_name.get(company_name, {})
            triplets.append(Triplet(
                source_name=company_name,
                source_type="Company",
                source_attributes={"name": company_name, "size_signal": company_data.get("size_signal"), "domain_summary": company_data.get("domain_summary")},
                target_name=cs["skill"],
                target_type="Skill",
                target_attributes={"name": cs["skill"]},
                relation="KNOWN_FOR",
                edge_attributes={},
            ))

        for cl in concepts.get("company_locations", []):
            company_name = cl["company"]
            company_data = companies_by_name.get(company_name, {})
            triplets.append(Triplet(
                source_name=company_name,
                source_type="Company",
                source_attributes={"name": company_name, "size_signal": company_data.get("size_signal"), "domain_summary": company_data.get("domain_summary")},
                target_name=cl["location"],
                target_type="Location",
                target_attributes={"name": cl["location"]},
                relation="BASED_IN",
                edge_attributes={},
            ))

        return triplets
