"""
Clear and re-ingest one or more organizations.

Usage:
    .venv/bin/python -m scripts.clear_and_reingest <org_id> [<org_id> ...]
"""
import asyncio
import sys
from pathlib import Path
from time import monotonic

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from graphiti_core import Graphiti
from graphiti_core.embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from neo4j import AsyncGraphDatabase

from src.config.database import neo4j_driver
from src.config.settings import get_settings
from src.main import NoOpCrossEncoder, PassthroughLLMClient
from src.ontology.validator import OntologyValidator
from src.service.concept_extractor import ConceptExtractor
from src.service.event_router import EventRouter
from src.service.graph_ingestion_service import GraphIngestionService
from src.service.handlers.decision_handler import DecisionHandler
from src.service.handlers.feedback_debrief_handler import FeedbackDebriefHandler
from src.service.handlers.feedback_handler import FeedbackHandler
from src.service.handlers.intake_handler import IntakeHandler
from src.service.handlers.interview_handler import InterviewHandler
from src.service.handlers.jd_handler import JDHandler
from src.service.handlers.plan_handler import PlanHandler
from src.service.handlers.question_summary_handler import QuestionSummaryHandler
from src.service.ingestion_tracker import IngestionTracker
from src.service.org_ingestion_service import OrgIngestionService
from src.service.supabase_fetcher import SupabaseFetcher

logger = structlog.get_logger(__name__)


async def clear_org(neo4j_uri: str, user: str, password: str, org_id: str) -> dict:
    driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(user, password))
    counts = {}
    try:
        async with driver.session() as session:
            r = await session.run(
                "MATCH (n) WHERE n.group_id = $g WITH count(n) AS c RETURN c", g=org_id
            )
            counts["nodes_before"] = (await r.single())["c"]
            r = await session.run(
                "MATCH ()-[e]->() WHERE e.group_id = $g WITH count(e) AS c RETURN c", g=org_id
            )
            counts["edges_before"] = (await r.single())["c"]

            await session.run(
                "MATCH (n) WHERE n.group_id = $g DETACH DELETE n", g=org_id
            )
            await session.run(
                "MATCH ()-[e]->() WHERE e.group_id = $g DELETE e", g=org_id
            )
            await session.run(
                "MATCH (r:IngestionRecord) WHERE r.org_id = $g DELETE r", g=org_id
            )

            r = await session.run(
                "MATCH (n) WHERE n.group_id = $g WITH count(n) AS c RETURN c", g=org_id
            )
            counts["nodes_after"] = (await r.single())["c"]
    finally:
        await driver.close()
    return counts


async def build_org_ingestion_service(settings) -> tuple[OrgIngestionService, Graphiti, SupabaseFetcher]:
    await neo4j_driver.connect(
        uri=settings.neo4j.uri,
        user=settings.neo4j.user,
        password=settings.neo4j.password,
    )

    graphiti = Graphiti(
        settings.neo4j.uri,
        settings.neo4j.user,
        settings.neo4j.password,
        llm_client=PassthroughLLMClient(),
        embedder=OpenAIEmbedder(OpenAIEmbedderConfig(api_key=settings.openai.api_key)),
        cross_encoder=NoOpCrossEncoder(),
    )
    await graphiti.build_indices_and_constraints()

    fetcher = SupabaseFetcher()
    validator = OntologyValidator()
    ingestion_service = GraphIngestionService(graphiti, validator)

    feedback_handler = FeedbackHandler(fetcher, ingestion_service)
    plan_handler = PlanHandler(fetcher, ingestion_service)
    decision_handler = DecisionHandler(fetcher, ingestion_service)

    concept_extractor = ConceptExtractor(api_key=settings.openai.api_key, model="gpt-4o-mini")
    qs_handler = QuestionSummaryHandler(fetcher, ingestion_service, concept_extractor)
    intake_handler = IntakeHandler(fetcher, ingestion_service, concept_extractor)
    fb_debrief_handler = FeedbackDebriefHandler(fetcher, ingestion_service, concept_extractor)
    interview_handler = InterviewHandler(fetcher, ingestion_service, concept_extractor)
    jd_handler = JDHandler(fetcher, ingestion_service, concept_extractor)

    event_router = EventRouter(
        feedback_handler, plan_handler, decision_handler,
        question_summaries_available=qs_handler,
        intake_transcript_available=intake_handler,
        feedback_debrief_available=fb_debrief_handler,
        interview_transcript_available=interview_handler,
        jd_available=jd_handler,
    )

    tracker = IngestionTracker(neo4j_driver)
    await tracker.ensure_index()

    return OrgIngestionService(fetcher, event_router, tracker), graphiti, fetcher


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    org_ids = sys.argv[1:]

    settings = get_settings()

    print(f"\n=== Clearing graph data for {len(org_ids)} org(s) ===")
    for org_id in org_ids:
        counts = await clear_org(
            settings.neo4j.uri, settings.neo4j.user, settings.neo4j.password, org_id
        )
        print(f"  {org_id}: {counts}")

    service, graphiti, fetcher = await build_org_ingestion_service(settings)
    try:
        for org_id in org_ids:
            print(f"\n=== Re-ingesting {org_id} ===")
            t0 = monotonic()
            result = await service.ingest_org(org_id)
            elapsed = monotonic() - t0
            print(f"  total_nodes: {result['total_nodes']}")
            print(f"  total_edges: {result['total_edges']}")
            print(f"  total_errors: {result['total_errors']}")
            print(f"  elapsed: {elapsed:.1f}s")
            print("  events:")
            for ev_type, ec in result["events"].items():
                print(f"    {ev_type}: processed={ec['processed']} skipped={ec['skipped']} errors={ec['errors']} nodes={ec['nodes']} edges={ec['edges']}")
            if result["errors"]:
                print("  first errors:")
                for err in result["errors"][:5]:
                    print(f"    - {err}")
    finally:
        await fetcher.close()
        await graphiti.close()
        await neo4j_driver.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
