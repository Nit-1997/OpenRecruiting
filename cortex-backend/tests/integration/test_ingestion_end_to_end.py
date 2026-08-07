"""The test that would have caught the graph being empty.

Everything below the queue was already covered by unit tests; what was never
covered was whether anything reaches Neo4j at all.

Needs a real Neo4j and a real Supabase, so the module is marked `live_infra`
and drops out of `make test-cortex`. Run it with:

    docker run --rm --network openrecruiting --env-file .env \
      -v "$PWD/cortex-backend:/app" -w /app openrecruiting-cortex-backend-test \
      python -m pytest tests/integration/test_ingestion_end_to_end.py -v -m live_infra

Every row this file writes lives in a throwaway organization created per test
and deleted on teardown, including its Neo4j subgraph. The failure path is
scoped to that org on purpose: a global claim would bump publish_count and
stamp last_error on real rows it had no intention of processing.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from graphiti_core import Graphiti
from graphiti_core.embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from supabase import create_async_client

from src.config.database import Neo4jDriver
from src.config.settings import get_settings
from src.main import NoOpCrossEncoder, PassthroughLLMClient
from src.ontology.validator import OntologyValidator
from src.service.concept_extractor import ConceptExtractor
from src.service.event_router import EventRouter
from src.service.graph_ingestion_service import GraphIngestionService
from src.service.handlers.candidate_evaluation_handler import CandidateEvaluationHandler
from src.service.handlers.candidate_profile_handler import CandidateProfileHandler
from src.service.handlers.decision_handler import DecisionHandler
from src.service.handlers.feedback_debrief_handler import FeedbackDebriefHandler
from src.service.handlers.feedback_handler import FeedbackHandler
from src.service.handlers.intake_handler import IntakeHandler
from src.service.handlers.intake_v2_handler import IntakeV2Handler
from src.service.handlers.interview_handler import InterviewHandler
from src.service.handlers.jd_handler import JDHandler
from src.service.handlers.plan_handler import PlanHandler
from src.service.handlers.question_summary_handler import QuestionSummaryHandler
from src.service.handlers.recruiter_insight_handler import RecruiterInsightHandler
from src.service.supabase_fetcher import SupabaseFetcher
from src.sync.brain_sync_cron import BrainSyncCron
from src.sync.event_processor import EventProcessor
from src.sync.event_queue import EventQueue
from src.sync.event_record import IngestionRecordRepo
from src.sync.tombstone import TombstoneService

pytestmark = [pytest.mark.live_infra, pytest.mark.asyncio]

SETTLED_HOURS = 72


@pytest_asyncio.fixture
async def supabase():
    settings = get_settings()
    if not (settings.supabase.url and settings.supabase.service_role_key):
        pytest.skip("Supabase credentials not configured")
    return await create_async_client(
        settings.supabase.url, settings.supabase.service_role_key
    )


@pytest_asyncio.fixture
async def neo4j():
    settings = get_settings()
    driver = Neo4jDriver()
    await driver.connect(
        uri=settings.neo4j.uri,
        user=settings.neo4j.user,
        password=settings.neo4j.password,
        database=settings.neo4j.database,
    )
    yield driver
    await driver.disconnect()


@pytest_asyncio.fixture
async def probe_org(supabase):
    """A throwaway organization. Every row and node the test writes hangs off
    it, so cleanup is one delete per table plus one `group_id` match in Neo4j."""
    org_id = str(uuid.uuid4())
    await supabase.table("organizations").insert({
        "id": org_id,
        "name": f"cortex ingestion probe {org_id[:8]}",
        "org_type": "team",
    }).execute()
    yield org_id
    await supabase.table("organizations").delete().eq("id", org_id).execute()


@pytest_asyncio.fixture
async def seeded_cortex_event(supabase, neo4j, probe_org):
    """A requisition past the settledness window.

    The `plan_created` row is not inserted directly: the requisitions trigger
    stamps it, which is the same path production takes. Only its last_touch_at
    is back-dated, so the row is eligible without the test faking eligibility.
    """
    requisition_id = str(uuid.uuid4())
    await supabase.table("requisitions").insert({
        "id": requisition_id,
        "organization_id": probe_org,
        "role_title": f"Cortex Probe Engineer {requisition_id[:8]}",
        "role_location": "Remote",
        "status": "planned",
        "must_have_skills": ["Python", "distributed systems"],
    }).execute()

    settled_at = datetime.now(timezone.utc) - timedelta(hours=SETTLED_HOURS)
    updated = await (
        supabase.table("cortex_events")
        .update({"last_touch_at": settled_at.isoformat()})
        .eq("event_type", "plan_created")
        .eq("source_id", requisition_id)
        .execute()
    )
    assert updated.data, "the requisitions trigger did not stamp a plan_created event"

    yield {
        "id": str(updated.data[0]["id"]),
        "org_id": probe_org,
        "requisition_id": requisition_id,
    }

    await supabase.table("cortex_ingestion_record").delete().eq(
        "source_id", requisition_id
    ).execute()
    await supabase.table("cortex_events").delete().eq(
        "source_id", requisition_id
    ).execute()
    await supabase.table("requisitions").delete().eq("id", requisition_id).execute()
    await neo4j.execute_write(
        "MATCH (n {group_id: $org_id}) DETACH DELETE n", {"org_id": probe_org}
    )


def _event_router(fetcher: SupabaseFetcher, ingestion: GraphIngestionService,
                  extractor: ConceptExtractor) -> EventRouter:
    """Every handler, mirroring main.py. `process_settled_events` claims across
    all orgs, so a partial router would route a stray real event to the wrong
    handler and write nonsense into the live graph."""
    return EventRouter(
        FeedbackHandler(fetcher, ingestion),
        PlanHandler(fetcher, ingestion),
        DecisionHandler(fetcher, ingestion),
        question_summaries_available=QuestionSummaryHandler(fetcher, ingestion, extractor),
        intake_transcript_available=IntakeHandler(fetcher, ingestion, extractor),
        feedback_debrief_available=FeedbackDebriefHandler(fetcher, ingestion, extractor),
        interview_transcript_available=InterviewHandler(fetcher, ingestion, extractor),
        jd_available=JDHandler(fetcher, ingestion, extractor),
        intake_v2_completed=IntakeV2Handler(fetcher, ingestion),
        recruiter_insight=RecruiterInsightHandler(fetcher, ingestion),
        candidate_profile_enriched=CandidateProfileHandler(fetcher, ingestion),
        candidate_evaluation=CandidateEvaluationHandler(fetcher, ingestion),
    )


@pytest_asyncio.fixture
async def cron(supabase, neo4j):
    settings = get_settings()
    if not settings.openai.api_key:
        pytest.skip("OPENAI_API_KEY not configured; graph ingestion is disabled")

    graphiti = Graphiti(
        settings.neo4j.uri,
        settings.neo4j.user,
        settings.neo4j.password,
        llm_client=PassthroughLLMClient(),
        embedder=OpenAIEmbedder(OpenAIEmbedderConfig(api_key=settings.openai.api_key)),
        cross_encoder=NoOpCrossEncoder(),
    )
    fetcher = SupabaseFetcher()
    ingestion = GraphIngestionService(
        graphiti, OntologyValidator(), database=settings.neo4j.database
    )
    router = _event_router(
        fetcher, ingestion,
        ConceptExtractor(api_key=settings.openai.api_key, model="gpt-4o-mini"),
    )
    yield BrainSyncCron(
        supabase=supabase,
        queue=EventQueue(supabase, lease_seconds=300, max_attempts=5),
        processor=EventProcessor(
            event_router=router,
            ingestion_repo=IngestionRecordRepo(supabase),
            tombstone=TombstoneService(neo4j),
        ),
        settledness_window_hours=48,
        batch_size=50,
    )
    await fetcher.close()
    await graphiti.close()


@pytest_asyncio.fixture
async def cron_with_failing_handler(supabase, neo4j):
    """A zero lease belongs in the fixture, not as a test-only parameter on the
    production method: with the default 300s the first claim would block the
    next five attempts."""
    class _ExplodingHandler:
        async def handle(self, *_args, **_kwargs):
            raise RuntimeError("handler exploded on purpose")

    class _OneHandlerRouter:
        def get_handler(self, _event_type):
            return _ExplodingHandler()

    return BrainSyncCron(
        supabase=supabase,
        queue=EventQueue(supabase, lease_seconds=0, max_attempts=5),
        processor=EventProcessor(
            event_router=_OneHandlerRouter(),
            ingestion_repo=IngestionRecordRepo(supabase),
            tombstone=TombstoneService(neo4j),
        ),
        settledness_window_hours=48,
        batch_size=50,
    )


async def _event_row(supabase, event_id: str) -> dict:
    resp = await (
        supabase.table("cortex_events")
        .select("publish_count,completed_at,last_error")
        .eq("id", event_id)
        .single()
        .execute()
    )
    return resp.data


async def test_a_settled_event_reaches_neo4j(seeded_cortex_event, cron, neo4j, supabase):
    before = (await neo4j.execute_read("MATCH (n) RETURN count(n) AS c"))[0]["c"]

    processed = await cron.process_settled_events()

    # `>= 1`, not `== 1`: cortex_events is shared, so a real settled row may be
    # claimed alongside the seeded one. The assertions below pin the seeded row.
    assert processed >= 1

    after = (await neo4j.execute_read("MATCH (n) RETURN count(n) AS c"))[0]["c"]
    assert after > before, "ingestion ran but wrote no nodes"

    probe_nodes = (await neo4j.execute_read(
        "MATCH (n {group_id: $org_id}) RETURN count(n) AS c",
        {"org_id": seeded_cortex_event["org_id"]},
    ))[0]["c"]
    assert probe_nodes > 0, "the seeded event ingested nothing"

    row = await _event_row(supabase, seeded_cortex_event["id"])
    assert row["completed_at"] is not None
    assert row["last_error"] is None


async def test_a_failing_event_is_retried_then_parked(
    seeded_cortex_event, cron_with_failing_handler, supabase
):
    for _ in range(6):
        await cron_with_failing_handler.process_org_now(seeded_cortex_event["org_id"])

    row = await _event_row(supabase, seeded_cortex_event["id"])
    assert row["completed_at"] is None
    assert row["last_error"] is not None
    assert row["publish_count"] <= 5, "attempt cap did not park the row"
