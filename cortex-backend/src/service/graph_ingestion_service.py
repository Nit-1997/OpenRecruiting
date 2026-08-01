import json
import uuid as uuid_mod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import monotonic

import structlog
from graphiti_core import Graphiti
from graphiti_core.nodes import EntityNode
from graphiti_core.edges import EntityEdge
from pydantic import ConfigDict

from src.ontology.normalizers import lookup_key
from src.ontology.validator import OntologyValidator, OntologyValidationError
from src.sync.provenance import Provenance, attach_provenance_to_attributes

logger = structlog.get_logger(__name__)


class EntityEdgeWithAttrs(EntityEdge):
    """EntityEdge extended with an `attributes` dict for provenance and edge metadata.

    Pydantic v2 does not allow setting arbitrary attributes on BaseModel instances,
    so we subclass and add `attributes` as a declared field. `EntityEdge.save()` only
    persists the fixed fields to Neo4j; provenance must be written via a separate Cypher SET.
    """
    model_config = ConfigDict(extra="ignore")
    attributes: dict = {}


CONCEPT_ENTITY_TYPES = {"Competency", "Skill", "Company", "Trait", "Market", "Location"}
CANONICALIZED_ENTITY_TYPES = {"Skill", "Company", "Trait", "Market", "Location"}
GRAPHITI_NS = uuid_mod.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


class CanonicalNameResolver:
    """Tier 1 lexical canonicalization. First-seen display name wins per (org, type, lookup_key).

    Lossless: original variants are appended to the entity's `aliases` list so context
    is preserved for downstream LLM traversal even though the display name is stable.
    """

    def __init__(self):
        self._cache: dict[tuple[str, str, str], dict] = {}

    def resolve(self, org_id: str, entity_type: str, name: str, attributes: dict) -> tuple[str, dict]:
        if entity_type not in CANONICALIZED_ENTITY_TYPES:
            return name, attributes
        key = (org_id, entity_type, lookup_key(name))
        existing = self._cache.get(key)
        if existing is None:
            attrs = dict(attributes)
            attrs.setdefault("aliases", [])
            self._cache[key] = {"display": name, "aliases": [name]}
            return name, attrs
        # canonicalize to the first-seen form, but record this variant as an alias
        if name not in existing["aliases"]:
            existing["aliases"].append(name)
        attrs = dict(attributes)
        attrs["aliases"] = list(existing["aliases"])
        return existing["display"], attrs


@dataclass
class Triplet:
    source_name: str
    source_type: str
    source_attributes: dict = field(default_factory=dict)
    source_id: str | None = None
    target_name: str = ""
    target_type: str = ""
    target_attributes: dict = field(default_factory=dict)
    target_id: str | None = None
    relation: str = ""
    edge_attributes: dict = field(default_factory=dict)


@dataclass
class IngestionResult:
    nodes_created: int = 0
    edges_created: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.errors:
            return "ingested"
        if self.nodes_created > 0 or self.edges_created > 0:
            return "partial"
        return "rejected"


class GraphIngestionService:
    def __init__(
        self,
        graphiti: Graphiti,
        validator: OntologyValidator,
        database: str = "neo4j",
    ):
        self._graphiti = graphiti
        self._validator = validator
        self._resolver = CanonicalNameResolver()
        self._database = database

    def _build_edge_uuid(self, triplet: Triplet, org_id: str, fact_str: str) -> str:
        parts = [org_id]
        if triplet.source_id:
            parts.append(triplet.source_id)
        if triplet.target_id:
            parts.append(triplet.target_id)
        parts.append(fact_str)
        return str(uuid_mod.uuid5(GRAPHITI_NS, ":".join(parts)))

    async def _verify_edge_saved(self, edge_uuid: str, fact_str: str) -> bool:
        driver = self._graphiti.driver
        records, _, _ = await driver.execute_query(
            "MATCH ()-[e:RELATES_TO {uuid: $uuid}]->() RETURN e.uuid LIMIT 1",
            {"uuid": edge_uuid},
            database_=self._database,
            routing_="r",
        )
        return len(records) > 0

    async def ingest_triplets(
        self, triplets: list[Triplet], org_id: str, provenance: Provenance | None = None
    ) -> IngestionResult:
        result = IngestionResult()
        t_start = monotonic()

        for i, triplet in enumerate(triplets):
            triplet.source_name, triplet.source_attributes = self._resolver.resolve(
                org_id, triplet.source_type, triplet.source_name, triplet.source_attributes
            )
            triplet.target_name, triplet.target_attributes = self._resolver.resolve(
                org_id, triplet.target_type, triplet.target_name, triplet.target_attributes
            )
            try:
                self._validator.validate_node(triplet.source_type, triplet.source_attributes)
                self._validator.validate_node(triplet.target_type, triplet.target_attributes)
                self._validator.validate_edge(triplet.source_type, triplet.target_type, triplet.relation)
                self._validator.validate_edge_attributes(triplet.relation, triplet.edge_attributes)
            except OntologyValidationError as e:
                logger.warning("triplet_validation_failed", error=e.message, triplet_source=triplet.source_name)
                result.errors.append(e.message)
                continue

            try:
                now = datetime.now(timezone.utc)

                def _node_uuid(t_id: str | None, t_type: str, name: str) -> str:
                    if t_id and t_type not in CONCEPT_ENTITY_TYPES:
                        return str(uuid_mod.uuid5(GRAPHITI_NS, t_id))
                    if t_type in CONCEPT_ENTITY_TYPES:
                        return str(uuid_mod.uuid5(GRAPHITI_NS, f"concept:{org_id}:{t_type}:{lookup_key(name)}"))
                    return str(uuid_mod.uuid4())

                source_uuid = _node_uuid(triplet.source_id, triplet.source_type, triplet.source_name)
                target_uuid = _node_uuid(triplet.target_id, triplet.target_type, triplet.target_name)

                source_node = EntityNode(
                    uuid=source_uuid,
                    name=triplet.source_name,
                    labels=[triplet.source_type],
                    group_id=org_id,
                    created_at=now,
                    summary=triplet.source_name,
                    attributes=triplet.source_attributes,
                )
                target_node = EntityNode(
                    uuid=target_uuid,
                    name=triplet.target_name,
                    labels=[triplet.target_type],
                    group_id=org_id,
                    created_at=now,
                    summary=triplet.target_name,
                    attributes=triplet.target_attributes,
                )

                fact_str = f"{triplet.source_name} {triplet.relation} {triplet.target_name}"
                if triplet.edge_attributes:
                    fact_str += f" ({json.dumps(triplet.edge_attributes)})"

                edge_uuid = self._build_edge_uuid(triplet, org_id, fact_str)

                edge_attrs = dict(triplet.edge_attributes)
                if provenance is not None:
                    edge_attrs = attach_provenance_to_attributes(edge_attrs, provenance)

                edge = EntityEdgeWithAttrs(
                    uuid=edge_uuid,
                    source_node_uuid=source_uuid,
                    target_node_uuid=target_uuid,
                    name=triplet.relation,
                    group_id=org_id,
                    created_at=now,
                    fact=fact_str,
                    episodes=[],
                    valid_at=now,
                    attributes=edge_attrs,
                )

                await self._graphiti.add_triplet(
                    source_node=source_node,
                    edge=edge,
                    target_node=target_node,
                )

                if provenance is not None:
                    try:
                        await self._graphiti.driver.execute_query(
                            "MATCH ()-[e:RELATES_TO {uuid: $uuid}]->() "
                            "SET e._source_event_type = $set, "
                            "    e._source_id = $sid, "
                            "    e._ingested_at = $iat, "
                            "    e._event_pk = $epk",
                            {
                                "uuid": edge_uuid,
                                "set": provenance.source_event_type,
                                "sid": provenance.source_id,
                                "iat": provenance.ingested_at.isoformat(),
                                "epk": provenance.event_pk,
                            },
                            database_=self._database,
                        )
                    except Exception as prov_err:
                        logger.warning(
                            "provenance_write_failed",
                            edge_uuid=edge_uuid,
                            error=str(prov_err),
                        )

                if not await self._verify_edge_saved(edge_uuid, fact_str):
                    msg = f"Edge silently dropped: {triplet.source_name}→{triplet.target_name} ({triplet.relation})"
                    logger.error("edge_save_silent_failure", edge_uuid=edge_uuid, fact=fact_str)
                    result.errors.append(msg)
                    continue

                result.nodes_created += 2
                result.edges_created += 1

            except Exception as e:
                logger.error("triplet_ingestion_failed", error=str(e), triplet_source=triplet.source_name)
                result.errors.append(f"Ingestion failed for {triplet.source_name}→{triplet.target_name}: {str(e)}")

        elapsed_ms = (monotonic() - t_start) * 1000
        logger.info(
            "triplet_batch_complete",
            org_id=org_id,
            triplet_count=len(triplets),
            nodes_created=result.nodes_created,
            edges_created=result.edges_created,
            errors=len(result.errors),
            elapsed_ms=round(elapsed_ms, 1),
        )

        return result
