import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import structlog

from src.model.ingestion import SourceRef
from src.service.graph_ingestion_service import IngestionResult as HandlerResult
from src.sync.event_record import IngestionRecord, IngestionRecordRepo
from src.sync.provenance import Provenance
from src.sync.tombstone import TombstoneService

logger = structlog.get_logger(__name__)


_SOURCE_REF_KEY = {
    "feedback_debrief_available": "candidate_round_id",
    "feedback_completed": "candidate_round_id",
    "interview_transcript_available": "candidate_round_id",
    "question_summaries_available": "candidate_round_id",
    "intake_transcript_available": "requisition_id",
    "plan_created": "requisition_id",
    "jd_available": "requisition_id",
    "decision_made": "candidate_id",
    "candidate_profile_enriched": "candidate_id",
    "intake_v2_completed": "session_id",
}


class IngestionFailure(Exception):
    """Raised when handler.handle() returned a non-success status. Lets SQS retry."""


class SqsConsumer:
    """Long-running consumer for the cortex-ingestion-events.fifo queue.

    For each message: decode → look up local IngestionRecord → branch first-ingest
    vs re-edit → call existing handler → upsert IngestionRecord on success.
    """

    def __init__(
        self,
        sqs_client: Any,
        queue_url: str,
        event_router: Any,
        ingestion_repo: IngestionRecordRepo,
        tombstone: TombstoneService,
        max_messages: int = 10,
        wait_seconds: int = 20,
        visibility_timeout: int = 300,
    ):
        self._sqs = sqs_client
        self._queue_url = queue_url
        self._router = event_router
        self._repo = ingestion_repo
        self._tombstone = tombstone
        self._max_messages = max_messages
        self._wait_seconds = wait_seconds
        self._visibility_timeout = visibility_timeout
        self._stop = asyncio.Event()

    async def handle_message(self, raw: dict) -> None:
        body = json.loads(raw["Body"])
        event_type: str = body["event_type"]
        source_id: str = body["source_id"]
        org_id: str = body["org_id"]
        incoming_touch = datetime.fromisoformat(body["last_touch_at"])
        event_pk: str = body["event_pk"]

        record = await self._repo.get(event_type=event_type, source_id=source_id)

        if record is not None and record.last_touch_at >= incoming_touch:
            logger.info(
                "stale_message_skipped",
                event_type=event_type,
                source_id=source_id,
                incoming=incoming_touch.isoformat(),
                already=record.last_touch_at.isoformat(),
            )
            return

        is_re_edit = record is not None
        if is_re_edit:
            await self._tombstone.tombstone_prior_edges(
                event_type=event_type,
                source_id=source_id,
                before=incoming_touch,
            )

        ref_key = _SOURCE_REF_KEY.get(event_type)
        if ref_key is None:
            raise IngestionFailure(f"unknown event_type {event_type}")

        ingested_at = datetime.now(timezone.utc)
        provenance = Provenance(
            source_event_type=event_type,
            source_id=source_id,
            ingested_at=ingested_at,
            event_pk=event_pk,
        )

        handler = self._router.get_handler(event_type)
        source_ref = SourceRef(**{ref_key: source_id})
        result: HandlerResult = await handler.handle(source_ref, org_id, provenance=provenance)

        if result.status not in ("ingested", "partial"):
            raise IngestionFailure(
                f"handler returned status={result.status} errors={result.errors[:3]}"
            )

        await self._repo.upsert(IngestionRecord(
            event_type=event_type,
            source_id=source_id,
            org_id=org_id,
            last_touch_at=incoming_touch,
            ingested_at=ingested_at,
            nodes_count=result.nodes_created,
            edges_count=result.edges_created,
            publish_count=int(body.get("publish_count", 1)),
        ))

        logger.info(
            "event_ingested",
            event_type=event_type,
            source_id=source_id,
            re_edit=is_re_edit,
            nodes=result.nodes_created,
            edges=result.edges_created,
        )

    async def run(self) -> None:
        logger.info("sqs_consumer_started", queue=self._queue_url)
        while not self._stop.is_set():
            try:
                resp = await asyncio.to_thread(
                    self._sqs.receive_message,
                    QueueUrl=self._queue_url,
                    MaxNumberOfMessages=self._max_messages,
                    WaitTimeSeconds=self._wait_seconds,
                    VisibilityTimeout=self._visibility_timeout,
                    AttributeNames=["All"],
                    MessageAttributeNames=["All"],
                )
            except Exception as e:
                logger.error("sqs_receive_failed", error=str(e))
                await asyncio.sleep(5)
                continue

            messages = resp.get("Messages", [])
            for msg in messages:
                try:
                    await self.handle_message(msg)
                    await asyncio.to_thread(
                        self._sqs.delete_message,
                        QueueUrl=self._queue_url,
                        ReceiptHandle=msg["ReceiptHandle"],
                    )
                except Exception as e:
                    logger.warning(
                        "message_handling_failed",
                        error=str(e),
                        msg_id=msg.get("MessageId"),
                    )
                    # Do not delete — let SQS visibility timeout handle retry/DLQ.

        logger.info("sqs_consumer_stopped")

    def stop(self) -> None:
        self._stop.set()
