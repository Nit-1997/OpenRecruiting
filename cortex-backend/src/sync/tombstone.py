from datetime import datetime

import structlog

from src.config.database import Neo4jDriver

logger = structlog.get_logger(__name__)


class TombstoneService:
    """Marks prior-batch edges as invalid_at = NOW() so re-emission stays clean.

    Provenance attributes (_source_event_type, _source_id, _ingested_at) are
    attached to every edge by GraphIngestionService when a Provenance is provided.
    Tombstoning targets edges whose _ingested_at is strictly older than the
    incoming batch's ingested_at, leaving everything else untouched.
    """

    _CYPHER = (
        "MATCH ()-[e]->() "
        "WHERE e._source_event_type = $event_type "
        "  AND e._source_id = $source_id "
        "  AND e._ingested_at < $before "
        "  AND (e.invalid_at IS NULL) "
        "SET e.invalid_at = datetime() "
        "RETURN count(e) AS tombstoned"
    )

    def __init__(self, neo4j: Neo4jDriver):
        self._neo4j = neo4j

    async def tombstone_prior_edges(
        self, event_type: str, source_id: str, before: datetime
    ) -> int:
        rows = await self._neo4j.execute_write(
            self._CYPHER,
            {
                "event_type": event_type,
                "source_id": source_id,
                "before": before.isoformat(),
            },
        )
        count = rows[0]["tombstoned"] if rows else 0
        logger.info(
            "tombstoned_prior_edges",
            event_type=event_type,
            source_id=source_id,
            count=count,
        )
        return count
