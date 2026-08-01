"""Parallel drain. Publishes all settled cortex_events, then concurrently consumes from SQS until empty."""
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

CONCURRENCY = 6


async def main():
    sb = await create_async_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])
    sqs = boto3.client('sqs', region_name=os.environ['AWS_REGION'])
    queue = os.environ['CORTEX_SQS_QUEUE_URL']

    # Publish in batches (1000 per call)
    cron = BrainSyncCron(sb, sqs, queue, settledness_window_hours=0, batch_size=1000)
    total_pub = 0
    while True:
        sent = await cron.publish_settled_events()
        total_pub += sent
        if sent == 0:
            break
        print(f'PUBLISH BATCH: {sent} (total={total_pub})')
    print(f'TOTAL PUBLISHED: {total_pub}')

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
                           max_messages=10, wait_seconds=10, visibility_timeout=600)

    summary = {}
    processed = 0
    start = time.time()
    sem = asyncio.Semaphore(CONCURRENCY)

    async def process_one(m):
        async with sem:
            body = json.loads(m['Body'])
            et = body['event_type']
            try:
                await consumer.handle_message(m)
                await asyncio.to_thread(sqs.delete_message, QueueUrl=queue, ReceiptHandle=m['ReceiptHandle'])
                return ('ok', et, None)
            except Exception as e:
                return ('fail', et, f'{type(e).__name__}: {str(e)[:200]}')

    empty_polls = 0
    while empty_polls < 3:
        resp = await asyncio.to_thread(sqs.receive_message,
            QueueUrl=queue, MaxNumberOfMessages=10, WaitTimeSeconds=10, VisibilityTimeout=600,
            AttributeNames=['All'], MessageAttributeNames=['All'])
        msgs = resp.get('Messages', [])
        if not msgs:
            empty_polls += 1
            continue
        empty_polls = 0
        results = await asyncio.gather(*[process_one(m) for m in msgs])
        for status, et, err in results:
            s = summary.setdefault(et, {'ok': 0, 'fail': 0, 'errors': []})
            s[status] += 1
            if err:
                s['errors'].append(err)
        processed += len(msgs)
        elapsed = time.time() - start
        rate = processed / elapsed if elapsed > 0 else 0
        print(f'[{int(elapsed)}s] processed={processed} rate={rate:.1f}/s')

    print('\n=== DRAIN SUMMARY ===')
    for et, s in sorted(summary.items()):
        print(f'  {et}: ok={s["ok"]} fail={s["fail"]}')
        for err in s['errors'][:5]:
            print(f'    ! {err}')
    print(f'Total time: {int(time.time() - start)}s')

    await fetcher.close()
    await g.close()
    await neo4j_driver.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
