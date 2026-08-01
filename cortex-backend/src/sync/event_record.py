from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class IngestionRecord:
    event_type: str
    source_id: str
    org_id: str
    last_touch_at: datetime
    ingested_at: datetime
    nodes_count: int
    edges_count: int
    publish_count: int


def _parse_dt(s: Any) -> datetime:
    if isinstance(s, datetime):
        return s
    return datetime.fromisoformat(str(s))


def _record_from_row(row: dict) -> IngestionRecord:
    return IngestionRecord(
        event_type=row["event_type"],
        source_id=str(row["source_id"]),
        org_id=str(row["org_id"]),
        last_touch_at=_parse_dt(row["last_touch_at"]),
        ingested_at=_parse_dt(row["ingested_at"]),
        nodes_count=int(row.get("nodes_count", 0)),
        edges_count=int(row.get("edges_count", 0)),
        publish_count=int(row.get("publish_count", 1)),
    )


class IngestionRecordRepo:
    """Postgres-backed CRUD for cortex_ingestion_record. The supabase client must be
    an async-capable supabase-py instance (or an equivalent that supports the
    .table().select().eq().maybe_single().execute() chain)."""

    TABLE = "cortex_ingestion_record"

    def __init__(self, supabase_client: Any):
        self._client = supabase_client

    async def get(self, event_type: str, source_id: str) -> IngestionRecord | None:
        resp = await (
            self._client.table(self.TABLE)
            .select("*")
            .eq("event_type", event_type)
            .eq("source_id", source_id)
            .maybe_single()
            .execute()
        )
        if not resp or not resp.data:
            return None
        return _record_from_row(resp.data)

    async def upsert(self, record: IngestionRecord) -> None:
        payload = {
            "event_type": record.event_type,
            "source_id": record.source_id,
            "org_id": record.org_id,
            "last_touch_at": record.last_touch_at.isoformat(),
            "ingested_at": record.ingested_at.isoformat(),
            "nodes_count": record.nodes_count,
            "edges_count": record.edges_count,
            "publish_count": record.publish_count,
        }
        await self._client.table(self.TABLE).upsert(
            payload, on_conflict="event_type,source_id"
        ).execute()
        logger.info(
            "ingestion_record_upserted",
            event_type=record.event_type,
            source_id=record.source_id,
            publish_count=record.publish_count,
        )
