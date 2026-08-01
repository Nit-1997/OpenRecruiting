"""Throwaway: publish all settled cortex_events, then poll SQS until empty and process."""
import asyncio, boto3, os, json, time
from supabase import create_async_client
from src.config.database import neo4j_driver
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
from src.sync.event_record import IngestionRecordRepo
from src.sync.sqs_consumer import SqsConsumer
from src.sync.tombstone import TombstoneService
from src.sync.brain_sync_cron import BrainSyncCron
from graphiti_core import Graphiti
from graphiti_core.embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from src.main import PassthroughLLMClient, NoOpCrossEncoder


async def main():
    sb = await create_async_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])
    sqs = boto3.client('sqs', region_name=os.environ['AWS_REGION'])
    queue = os.environ['CORTEX_SQS_QUEUE_URL']

    cron = BrainSyncCron(sb, sqs, queue, settledness_window_hours=0)
    sent = await cron.publish_settled_events()
    print(f'PUBLISHED: {sent}')

    await neo4j_driver.connect(uri=os.environ['NEO4J_URI'], user=os.environ['NEO4J_USER'], password=os.environ['NEO4J_PASSWORD'])
    g = Graphiti(os.environ['NEO4J_URI'], os.environ['NEO4J_USER'], os.environ['NEO4J_PASSWORD'],
                 llm_client=PassthroughLLMClient(),
                 embedder=OpenAIEmbedder(OpenAIEmbedderConfig(api_key=os.environ['OPENAI_API_KEY'])),
                 cross_encoder=NoOpCrossEncoder())
    await g.build_indices_and_constraints()
    fetcher = SupabaseFetcher()
    ingestion = GraphIngestionService(g, OntologyValidator())
    ce = ConceptExtractor(api_key=os.environ['OPENAI_API_KEY'], model='gpt-4o-mini')
    router = EventRouter(
        FeedbackHandler(fetcher, ingestion), PlanHandler(fetcher, ingestion), DecisionHandler(fetcher, ingestion),
        question_summaries_available=QuestionSummaryHandler(fetcher, ingestion, ce),
        intake_transcript_available=IntakeHandler(fetcher, ingestion, ce),
        feedback_debrief_available=FeedbackDebriefHandler(fetcher, ingestion, ce),
        interview_transcript_available=InterviewHandler(fetcher, ingestion, ce),
        jd_available=JDHandler(fetcher, ingestion, ce),
    )
    consumer = SqsConsumer(sqs, queue, router, IngestionRecordRepo(sb), TombstoneService(neo4j_driver),
                           max_messages=10, wait_seconds=10, visibility_timeout=300)

    summary = {}  # event_type -> {ok, fail, total_nodes, total_edges, re_edits}
    empty_polls = 0
    while empty_polls < 2:
        resp = await asyncio.to_thread(sqs.receive_message,
            QueueUrl=queue, MaxNumberOfMessages=10, WaitTimeSeconds=10, VisibilityTimeout=300,
            AttributeNames=['All'], MessageAttributeNames=['All'])
        msgs = resp.get('Messages', [])
        if not msgs:
            empty_polls += 1
            continue
        empty_polls = 0
        for m in msgs:
            body = json.loads(m['Body'])
            et = body['event_type']
            summary.setdefault(et, {'ok': 0, 'fail': 0, 'errors': []})
            try:
                # Detect re-edit by checking ingestion_record before
                rec = await IngestionRecordRepo(sb).get(et, body['source_id'])
                is_re_edit = rec is not None
                await consumer.handle_message(m)
                await asyncio.to_thread(sqs.delete_message, QueueUrl=queue, ReceiptHandle=m['ReceiptHandle'])
                summary[et]['ok'] += 1
                summary[et]['re_edit'] = summary[et].get('re_edit', 0) + (1 if is_re_edit else 0)
            except Exception as e:
                summary[et]['fail'] += 1
                summary[et]['errors'].append(f'{type(e).__name__}: {str(e)[:200]}')
                print(f'FAIL {et} src={body["source_id"]}: {type(e).__name__}: {str(e)[:200]}')

    print('\n=== DRAIN SUMMARY ===')
    for et, s in sorted(summary.items()):
        print(f'  {et}: ok={s["ok"]} fail={s["fail"]} re_edits={s.get("re_edit", 0)}')
        for err in s['errors'][:3]:
            print(f'    ! {err}')

    await fetcher.close()
    await g.close()
    await neo4j_driver.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
