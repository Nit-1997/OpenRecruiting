from datetime import datetime, timezone
from typing import Any

import structlog

from src.model.ingestion import SourceRef
from src.service.graph_ingestion_service import IngestionResult as HandlerResult
from src.sync.event_queue import ClaimedEvent
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
    """Raised when handler.handle() returned a non-success status. The caller
    marks the row failed; lease expiry re-offers it until the attempt cap."""


class EventProcessor:
    """Ingests one claimed cortex_events row.

    Look up the local IngestionRecord → branch first-ingest vs re-edit → call the
    existing handler → upsert IngestionRecord on success. Transport-free: it
    neither claims nor completes rows, so the queue owns all retry state.
    """

    def __init__(
        self,
        event_router: Any,
        ingestion_repo: IngestionRecordRepo,
        tombstone: TombstoneService,
    ):
        self._router = event_router
        self._repo = ingestion_repo
        self._tombstone = tombstone

    async def process(self, event: ClaimedEvent) -> None:
        event_type = event.event_type
        source_id = event.source_id
        org_id = event.org_id
        incoming_touch = event.last_touch_at
        event_pk = event.id

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
            publish_count=event.publish_count,
        ))

        logger.info(
            "event_ingested",
            event_type=event_type,
            source_id=source_id,
            re_edit=is_re_edit,
            nodes=result.nodes_created,
            edges=result.edges_created,
        )
