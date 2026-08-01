import structlog

from src.config.database import Neo4jDriver

logger = structlog.get_logger(__name__)


class IngestionTracker:
    def __init__(self, neo4j: Neo4jDriver):
        self._neo4j = neo4j

    async def ensure_index(self) -> None:
        await self._neo4j.execute_write(
            "CREATE INDEX ingestion_record_lookup IF NOT EXISTS "
            "FOR (r:IngestionRecord) ON (r.event_type, r.source_ref)"
        )

    async def is_ingested(self, event_type: str, source_ref: str, source_updated_at: str) -> bool:
        records = await self._neo4j.execute_read(
            "MATCH (r:IngestionRecord {event_type: $event_type, source_ref: $source_ref}) "
            "WHERE r.source_updated_at = $updated_at "
            "RETURN r LIMIT 1",
            {"event_type": event_type, "source_ref": source_ref, "updated_at": source_updated_at},
        )
        return len(records) > 0

    async def record_ingestion(self, event_type: str, source_ref: str, org_id: str, source_updated_at: str) -> None:
        await self._neo4j.execute_write(
            "MERGE (r:IngestionRecord {event_type: $event_type, source_ref: $source_ref}) "
            "SET r.org_id = $org_id, r.source_updated_at = $updated_at, r.ingested_at = datetime()",
            {"event_type": event_type, "source_ref": source_ref, "org_id": org_id, "updated_at": source_updated_at},
        )

    async def clear_org(self, org_id: str) -> int:
        records = await self._neo4j.execute_write(
            "MATCH (r:IngestionRecord {org_id: $org_id}) DELETE r RETURN count(r) AS deleted",
            {"org_id": org_id},
        )
        return records[0]["deleted"] if records else 0
