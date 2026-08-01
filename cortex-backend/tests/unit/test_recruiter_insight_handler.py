"""Tests for RecruiterInsightHandler — the synchronous `recruiter_insight` ingest path.

Mocks Graphiti / GraphIngestionService; never hits Neo4j. Covers the two write
paths (decision_rationale → add_episode, recruiter_preference → ingest_triplets),
the no-triplet episode fallback, best-effort episode failure, unknown-kind no-op,
and event_router registration.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.service.graph_ingestion_service import IngestionResult, Triplet
from src.service.handlers.recruiter_insight_handler import RecruiterInsightHandler


def _make_handler():
    ingestion = MagicMock()
    ingestion.ingest_triplets = AsyncMock(
        return_value=IngestionResult(nodes_created=2, edges_created=1, errors=[])
    )
    graphiti = MagicMock()
    graphiti.add_episode = AsyncMock()
    ingestion._graphiti = graphiti

    handler = RecruiterInsightHandler(fetcher=MagicMock(), ingestion_service=ingestion)
    return handler, ingestion, graphiti


@pytest.mark.asyncio
async def test_decision_rationale_calls_add_episode():
    handler, ingestion, graphiti = _make_handler()
    payload = {
        "org_id": "org-a",
        "requisition_id": "req-1",
        "candidate_id": "cand-1",
        "kind": "decision_rationale",
        "insight_text": "Picked Alice over Bob because of stronger system-design signal.",
        "triplet": None,
    }

    await handler.handle_direct(payload, org_id="org-a")

    graphiti.add_episode.assert_awaited_once()
    kwargs = graphiti.add_episode.await_args.kwargs
    assert kwargs["episode_body"] == payload["insight_text"]
    assert kwargs["group_id"] == "org-a"
    assert kwargs["reference_time"] is not None
    assert kwargs["name"] == "recruiter_insight:req-1"
    # decision_rationale must NOT take the structured triplet path
    ingestion.ingest_triplets.assert_not_awaited()


@pytest.mark.asyncio
async def test_decision_rationale_name_falls_back_to_org_when_no_requisition():
    handler, _ingestion, graphiti = _make_handler()
    payload = {
        "org_id": "org-a",
        "requisition_id": None,
        "kind": "decision_rationale",
        "insight_text": "General hiring-bar note.",
    }

    await handler.handle_direct(payload, org_id="org-a")

    assert graphiti.add_episode.await_args.kwargs["name"] == "recruiter_insight:org"


@pytest.mark.asyncio
async def test_recruiter_preference_with_triplet_calls_ingest_triplets():
    handler, ingestion, graphiti = _make_handler()
    payload = {
        "org_id": "org-a",
        "requisition_id": "req-1",
        "kind": "recruiter_preference",
        "insight_text": "Prefers candidates with deep ownership.",
        "triplet": {"subject": "Senior BE", "predicate": "values", "object": "ownership"},
    }

    result = await handler.handle_direct(payload, org_id="org-a")

    ingestion.ingest_triplets.assert_awaited_once()
    triplets, ingest_org_id = ingestion.ingest_triplets.await_args.args[:2]
    assert ingest_org_id == "org-a"
    assert len(triplets) == 1
    t: Triplet = triplets[0]
    # ontology-valid mapping: Requisition -[VALUES]-> Trait
    assert t.source_type == "Requisition"
    assert t.source_id == "req-1"
    assert t.target_type == "Trait"
    assert t.target_name == "ownership"
    assert t.relation == "VALUES"
    # the recruiter's predicate is preserved as edge evidence
    assert t.edge_attributes.get("evidence") == "values"
    # preference path does NOT also write an episode
    graphiti.add_episode.assert_not_awaited()
    assert result.edges_created == 1


@pytest.mark.asyncio
async def test_recruiter_preference_triplet_validates_against_ontology():
    """The triplet must pass through the REAL GraphIngestionService validator."""
    from src.ontology.validator import OntologyValidator
    from src.service.graph_ingestion_service import GraphIngestionService

    graphiti = MagicMock()
    graphiti.add_triplet = AsyncMock()
    real_ingestion = GraphIngestionService(graphiti, OntologyValidator())
    # _verify_edge_saved would hit the driver — stub it to confirm the save.
    real_ingestion._verify_edge_saved = AsyncMock(return_value=True)

    handler = RecruiterInsightHandler(fetcher=MagicMock(), ingestion_service=real_ingestion)
    payload = {
        "org_id": "org-a",
        "requisition_id": "req-1",
        "kind": "recruiter_preference",
        "insight_text": "Prefers ownership.",
        "triplet": {"subject": "Senior BE", "predicate": "values", "object": "ownership"},
    }

    result = await handler.handle_direct(payload, org_id="org-a")

    # no ontology errors → the triplet is a valid Requisition→Trait VALUES edge
    assert result.errors == []
    graphiti.add_triplet.assert_awaited_once()


@pytest.mark.asyncio
async def test_recruiter_preference_without_triplet_falls_back_to_episode():
    handler, ingestion, graphiti = _make_handler()
    payload = {
        "org_id": "org-a",
        "requisition_id": "req-1",
        "kind": "recruiter_preference",
        "insight_text": "Prefers ownership but couldn't structure it.",
        "triplet": None,
    }

    await handler.handle_direct(payload, org_id="org-a")

    # insight not dropped: it lands as an episode instead
    graphiti.add_episode.assert_awaited_once()
    assert graphiti.add_episode.await_args.kwargs["episode_body"] == payload["insight_text"]
    ingestion.ingest_triplets.assert_not_awaited()


@pytest.mark.asyncio
async def test_episode_failure_is_swallowed_best_effort():
    handler, ingestion, graphiti = _make_handler()
    graphiti.add_episode = AsyncMock(side_effect=RuntimeError("Neo4j down"))
    ingestion._graphiti = graphiti
    payload = {
        "org_id": "org-a",
        "requisition_id": "req-1",
        "kind": "decision_rationale",
        "insight_text": "Some rationale.",
    }

    # must not raise
    result = await handler.handle_direct(payload, org_id="org-a")
    assert result is not None
    assert any("episode" in e.lower() for e in result.errors)


@pytest.mark.asyncio
async def test_unknown_kind_is_noop():
    handler, ingestion, graphiti = _make_handler()
    payload = {
        "org_id": "org-a",
        "requisition_id": "req-1",
        "kind": "something_else",
        "insight_text": "ignored",
    }

    result = await handler.handle_direct(payload, org_id="org-a")

    graphiti.add_episode.assert_not_awaited()
    ingestion.ingest_triplets.assert_not_awaited()
    assert result is not None  # no raise


@pytest.mark.asyncio
async def test_empty_insight_text_is_noop():
    handler, ingestion, graphiti = _make_handler()
    payload = {"org_id": "org-a", "kind": "decision_rationale", "insight_text": "   "}

    result = await handler.handle_direct(payload, org_id="org-a")

    graphiti.add_episode.assert_not_awaited()
    ingestion.ingest_triplets.assert_not_awaited()
    assert result.errors == []


@pytest.mark.asyncio
async def test_preference_triplet_missing_object_falls_back_to_episode():
    handler, ingestion, graphiti = _make_handler()
    payload = {
        "org_id": "org-a",
        "requisition_id": "req-1",
        "kind": "recruiter_preference",
        "insight_text": "Prefers ownership.",
        "triplet": {"subject": "Senior BE", "predicate": "values", "object": ""},
    }

    await handler.handle_direct(payload, org_id="org-a")

    graphiti.add_episode.assert_awaited_once()
    ingestion.ingest_triplets.assert_not_awaited()


def test_event_router_registers_recruiter_insight():
    from src.service.event_router import EventRouter

    handler, _ingestion, _graphiti = _make_handler()
    router = EventRouter(
        feedback_handler=MagicMock(),
        plan_handler=MagicMock(),
        decision_handler=MagicMock(),
        recruiter_insight=handler,
    )
    assert router.get_handler("recruiter_insight") is handler
    assert "recruiter_insight" in router.supported_events
