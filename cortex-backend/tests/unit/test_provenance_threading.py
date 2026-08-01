from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ontology.validator import OntologyValidator
from src.service.graph_ingestion_service import GraphIngestionService, Triplet
from src.sync.provenance import Provenance


@pytest.fixture
def graphiti():
    g = MagicMock()
    g.add_triplet = AsyncMock()
    g.driver = MagicMock()
    g.driver.execute_query = AsyncMock(return_value=([{"e.uuid": "edge-uuid"}], None, None))
    return g


@pytest.mark.asyncio
async def test_ingest_triplets_attaches_provenance_to_edge(graphiti):
    service = GraphIngestionService(graphiti, OntologyValidator())
    prov = Provenance(
        source_event_type="feedback_debrief_available",
        source_id="cr-1",
        ingested_at=datetime(2026, 5, 9, tzinfo=timezone.utc),
        event_pk="ev-1",
    )

    triplets = [
        Triplet(
            source_name="Sarah",
            source_type="Candidate",
            source_id="cand-1",
            source_attributes={"name": "Sarah", "candidate_ref": "cand-1"},
            target_name="System Design",
            target_type="Competency",
            target_attributes={"heading": "System Design"},
            relation="STRONG_IN",
            edge_attributes={"weight": 0.8},
        )
    ]

    await service.ingest_triplets(triplets, org_id="org-1", provenance=prov)

    assert graphiti.add_triplet.await_count == 1
    call_args = graphiti.add_triplet.await_args
    edge = call_args.kwargs["edge"]
    assert edge.attributes["_source_event_type"] == "feedback_debrief_available"
    assert edge.attributes["_source_id"] == "cr-1"
    assert edge.attributes["_event_pk"] == "ev-1"
    assert edge.attributes["weight"] == 0.8


@pytest.mark.asyncio
async def test_ingest_triplets_without_provenance_omits_keys(graphiti):
    service = GraphIngestionService(graphiti, OntologyValidator())
    triplets = [
        Triplet(
            source_name="Sarah",
            source_type="Candidate",
            source_id="cand-1",
            source_attributes={"name": "Sarah", "candidate_ref": "cand-1"},
            target_name="System Design",
            target_type="Competency",
            target_attributes={"heading": "System Design"},
            relation="STRONG_IN",
            edge_attributes={"weight": 0.8},
        )
    ]
    await service.ingest_triplets(triplets, org_id="org-1")
    edge = graphiti.add_triplet.await_args.kwargs["edge"]
    assert "_source_event_type" not in edge.attributes
    assert edge.attributes["weight"] == 0.8
