from contextlib import asynccontextmanager

import boto3
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from graphiti_core import Graphiti
from graphiti_core.llm_client.client import LLMClient
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.cross_encoder.client import CrossEncoderClient
from supabase import create_async_client

from src.config.settings import get_settings
from src.config.database import neo4j_driver
from src.sync.brain_sync_cron import BrainSyncCron
from src.sync.event_record import IngestionRecordRepo
from src.sync.tombstone import TombstoneService


class PassthroughLLMClient(LLMClient):
    def __init__(self):
        super().__init__(config=LLMConfig(api_key="unused"))

    async def _generate_response(self, *args, **kwargs) -> dict:
        return {}

    async def generate_response(self, messages, response_model=None, **kwargs) -> dict:
        if response_model is not None and response_model.__name__ == "NodeResolutions":
            import json, re
            # First-class entities (have stable real-id-based UUIDs); never merge by name.
            # Concept entities (no real-id) can dedup by name.
            CONCEPT_LABELS = {"Skill", "Company", "Trait", "Market", "Location", "Competency"}

            def _is_concept(node: dict) -> bool:
                labels = node.get("labels") or node.get("entity_types") or []
                if isinstance(labels, str):
                    labels = [labels]
                return any(lbl in CONCEPT_LABELS for lbl in labels)

            text = messages[-1].content if messages else ""
            match = re.search(r"<ENTITIES>\s*(.+?)\s*</ENTITIES>", text, re.DOTALL)
            if match:
                nodes = json.loads(match.group(1))
                resolutions = []
                for n in nodes:
                    dup_idx = -1
                    candidates = n.get("duplication_candidates", [])
                    name_lower = n["name"].strip().lower()
                    new_is_concept = _is_concept(n)
                    for cand in candidates:
                        if cand["name"].strip().lower() != name_lower:
                            continue
                        # Only allow merge when BOTH new node and candidate look like concept entities,
                        # OR labels are unknown (fall back to name match — preserves prior behavior).
                        cand_is_concept = _is_concept(cand)
                        labels_known = bool(n.get("labels") or n.get("entity_types") or cand.get("labels") or cand.get("entity_types"))
                        if (new_is_concept and cand_is_concept) or not labels_known:
                            dup_idx = cand["idx"]
                            break
                    resolutions.append({"id": n["id"], "duplicate_idx": dup_idx, "name": n["name"]})
                return {"entity_resolutions": resolutions}
            return {"entity_resolutions": [
                {"id": 0, "duplicate_idx": -1, "name": "source"},
                {"id": 1, "duplicate_idx": -1, "name": "target"},
            ]}
        return {"duplicate_fact_id": -1, "contradicted_facts": []}


class NoOpCrossEncoder(CrossEncoderClient):
    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        return [(p, 0.0) for p in passages]
from src.controller.health_controller import router as health_router
from src.controller.ingestion_controller import (
    router as ingestion_router,
    set_event_router,
    set_org_ingestion_service,
    set_brain_sync_cron,
    set_force_publish_job_service,
    set_org_ingest_job_service,
)
from src.controller.debrief_controller import (
    router as debrief_router,
    set_debrief_service,
)
from src.middleware.request_logging import RequestLoggingMiddleware
from src.exceptions.handlers import register_exception_handlers
from src.ontology.validator import OntologyValidator
from src.service.supabase_fetcher import SupabaseFetcher
from src.service.graph_ingestion_service import GraphIngestionService
from src.service.event_router import EventRouter
from src.service.concept_extractor import ConceptExtractor
from src.service.handlers.feedback_handler import FeedbackHandler
from src.service.handlers.plan_handler import PlanHandler
from src.service.handlers.decision_handler import DecisionHandler
from src.service.handlers.question_summary_handler import QuestionSummaryHandler
from src.service.handlers.intake_handler import IntakeHandler
from src.service.handlers.feedback_debrief_handler import FeedbackDebriefHandler
from src.service.handlers.interview_handler import InterviewHandler
from src.service.handlers.jd_handler import JDHandler
from src.service.handlers.intake_v2_handler import IntakeV2Handler
from src.service.handlers.recruiter_insight_handler import RecruiterInsightHandler
from src.service.handlers.candidate_profile_handler import CandidateProfileHandler
from src.service.handlers.candidate_evaluation_handler import CandidateEvaluationHandler
from src.service.force_publish_job_service import ForcePublishJobService
from src.service.org_ingest_job_service import OrgIngestJobService
from src.service.org_ingestion_service import OrgIngestionService
from src.service.ingestion_tracker import IngestionTracker
from src.service.debrief.debrief_service import DebriefService
from src.service.debrief.supabase_scaffold import SupabaseScaffold
from src.service.debrief.graph_reader import DebriefGraphReader
from src.service.debrief.scorer import DebriefScorer
from src.service.debrief.theme_builder import ThemeBuilder
from src.service.debrief.prose_synthesizer import ProseSynthesizer
from src.service.debrief.packet_builder import PacketBuilder

logger = structlog.get_logger(__name__)

_graphiti: Graphiti | None = None
_fetcher: SupabaseFetcher | None = None
_scheduler: AsyncIOScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graphiti, _fetcher
    settings = get_settings()

    await neo4j_driver.connect(
        uri=settings.neo4j.uri,
        user=settings.neo4j.user,
        password=settings.neo4j.password,
        database=settings.neo4j.database,
    )

    # Graph ingestion needs an embedding model, so the whole pipeline below is
    # gated on an OpenAI key. Without one the service still starts and serves
    # /health and read-only graph queries -- an absent key disables a feature
    # rather than crash-looping the container.
    if not settings.openai.api_key:
        logger.warning(
            "graph_ingestion_disabled",
            reason="OPENAI_API_KEY not set; embedding and concept extraction unavailable",
        )
    else:
        _graphiti = Graphiti(
            settings.neo4j.uri,
            settings.neo4j.user,
            settings.neo4j.password,
            llm_client=PassthroughLLMClient(),
            embedder=OpenAIEmbedder(OpenAIEmbedderConfig(api_key=settings.openai.api_key)),
            cross_encoder=NoOpCrossEncoder(),
        )

        await _graphiti.build_indices_and_constraints()
        logger.info("graphiti_indices_built")

        _fetcher = SupabaseFetcher()
        validator = OntologyValidator()
        ingestion_service = GraphIngestionService(
            _graphiti, validator, database=settings.neo4j.database
        )

        feedback_handler = FeedbackHandler(_fetcher, ingestion_service)
        plan_handler = PlanHandler(_fetcher, ingestion_service)
        decision_handler = DecisionHandler(_fetcher, ingestion_service)

        concept_extractor = ConceptExtractor(
            api_key=settings.openai.api_key,
            model="gpt-4o-mini",
        )
        qs_handler = QuestionSummaryHandler(_fetcher, ingestion_service, concept_extractor)
        intake_handler = IntakeHandler(_fetcher, ingestion_service, concept_extractor)
        feedback_debrief_handler = FeedbackDebriefHandler(_fetcher, ingestion_service, concept_extractor)
        interview_handler = InterviewHandler(_fetcher, ingestion_service, concept_extractor)
        jd_handler = JDHandler(_fetcher, ingestion_service, concept_extractor)
        intake_v2_handler = IntakeV2Handler(_fetcher, ingestion_service)
        recruiter_insight_handler = RecruiterInsightHandler(_fetcher, ingestion_service)
        candidate_profile_handler = CandidateProfileHandler(_fetcher, ingestion_service)
        candidate_evaluation_handler = CandidateEvaluationHandler(_fetcher, ingestion_service)

        event_router = EventRouter(
            feedback_handler, plan_handler, decision_handler,
            question_summaries_available=qs_handler,
            intake_transcript_available=intake_handler,
            feedback_debrief_available=feedback_debrief_handler,
            interview_transcript_available=interview_handler,
            jd_available=jd_handler,
            intake_v2_completed=intake_v2_handler,
            recruiter_insight=recruiter_insight_handler,
            candidate_profile_enriched=candidate_profile_handler,
            candidate_evaluation=candidate_evaluation_handler,
        )
        set_event_router(event_router)

        tracker = IngestionTracker(neo4j_driver)
        await tracker.ensure_index()

        org_ingestion_service = OrgIngestionService(_fetcher, event_router, tracker)
        set_org_ingestion_service(org_ingestion_service)

        # Debrief skill (spec §8): the only service with BOTH the Neo4j driver and a
        # Supabase fetcher. Reuses the shared `_fetcher`, `neo4j_driver` and the same
        # ConceptExtractor LLM path used by the ingestion handlers.
        debrief_service = DebriefService(
            scaffold=SupabaseScaffold(_fetcher),
            graph_reader=DebriefGraphReader(neo4j_driver),
            scorer=DebriefScorer(),
            theme_builder=ThemeBuilder(),
            prose_synthesizer=ProseSynthesizer(concept_extractor),
            packet_builder=PacketBuilder(),
        )
        set_debrief_service(debrief_service)

    supabase_async_client = None
    if settings.supabase.url and settings.supabase.service_role_key:
        supabase_async_client = await create_async_client(
            settings.supabase.url, settings.supabase.service_role_key
        )
        set_org_ingest_job_service(OrgIngestJobService(supabase_async_client))
        logger.info("org_ingest_job_service_initialized")
    else:
        logger.warning(
            "org_ingest_job_service_disabled",
            reason="Supabase URL or service_role_key missing",
        )

    if settings.sync.enabled and settings.sync.sqs_queue_url:
        sqs_client = boto3.client("sqs", region_name=settings.sync.aws_region)
        supabase_client = supabase_async_client
        if supabase_client is None:
            supabase_client = await create_async_client(
                settings.supabase.url, settings.supabase.service_role_key
            )
        ingestion_repo = IngestionRecordRepo(supabase_client)
        tombstone = TombstoneService(neo4j_driver)

        global _scheduler
        cron = BrainSyncCron(
            supabase=supabase_client,
            sqs_client=sqs_client,
            queue_url=settings.sync.sqs_queue_url,
            settledness_window_hours=settings.sync.settledness_window_hours,
            batch_size=settings.sync.publish_batch_size,
        )
        set_brain_sync_cron(cron)
        set_force_publish_job_service(ForcePublishJobService(supabase_client))
        _scheduler = AsyncIOScheduler(timezone="UTC")
        _scheduler.add_job(
            cron.publish_settled_events,
            trigger=IntervalTrigger(hours=settings.sync.publisher_interval_hours),
            id="brain_sync_publisher",
            max_instances=1,
            coalesce=True,
        )
        _scheduler.add_job(
            cron.reconcile,
            trigger=CronTrigger(day_of_week="sun", hour=8, minute=0),
            id="brain_sync_reconciliation",
            max_instances=1,
            coalesce=True,
        )
        _scheduler.start()
        logger.info("brain_sync_started",
                    queue=settings.sync.sqs_queue_url,
                    publisher_hours=settings.sync.publisher_interval_hours)
    else:
        logger.info("brain_sync_disabled",
                    reason="sync.enabled=False" if not settings.sync.enabled else "no sqs_queue_url")

    logger.info("cortex_started", neo4j=settings.neo4j.uri)

    yield

    if _scheduler is not None:
        _scheduler.shutdown(wait=False)

    if _fetcher:
        await _fetcher.close()
        _fetcher = None
    if _graphiti:
        await _graphiti.close()
        _graphiti = None
    await neo4j_driver.disconnect()


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=settings.app.name,
        version=settings.app.version,
        description=settings.app.description,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors.allowed_origins,
        allow_credentials=True,
        allow_methods=settings.cors.allowed_methods,
        allow_headers=settings.cors.allowed_headers,
    )
    application.add_middleware(RequestLoggingMiddleware)

    register_exception_handlers(application)

    application.include_router(health_router, prefix="/api/v1")
    application.include_router(ingestion_router, prefix="/api/v1")
    application.include_router(debrief_router, prefix="/api/v1")

    return application


app = create_app()
