from unittest.mock import AsyncMock, MagicMock
import pytest
from src.service.handlers.candidate_evaluation_handler import CandidateEvaluationHandler


def _payload():
    return {
        "candidate_id": "cand-1", "candidate_name": "Jenna", "status": "active",
        "evaluations": [{
            "interviewer_id": "u-1", "interviewer_name": "Mark", "recommendation": "strong_yes",
            "interview_id": "iv-1", "submitted_at": "2026-06-13T10:00:00Z",
            "attributes": [{"name": "System Design", "rating": "yes", "note": "solid"}],
        }],
    }


def _handler():
    return CandidateEvaluationHandler(fetcher=MagicMock(), ingestion_service=MagicMock())


def test_builds_evaluated_and_assessed_on_triplets():
    triplets = _handler().build_triplets_from_payload(_payload(), "org-a")
    rels = sorted(t.relation for t in triplets)
    assert rels == ["ASSESSED_ON", "EVALUATED"]
    evaluated = next(t for t in triplets if t.relation == "EVALUATED")
    assert evaluated.source_type == "Interviewer" and evaluated.source_id == "u-1"
    assert evaluated.target_type == "Candidate" and evaluated.target_id == "cand-1"
    assessed = next(t for t in triplets if t.relation == "ASSESSED_ON")
    assert assessed.source_type == "Candidate" and assessed.target_type == "Competency"
    assert assessed.target_id is None  # concept → no id
    assert assessed.edge_attributes["round_rating"] == "yes"


def test_missing_candidate_id_returns_empty():
    assert _handler().build_triplets_from_payload({"evaluations": []}, "org-a") == []


@pytest.mark.asyncio
async def test_triplets_validate_against_ontology():
    from src.ontology.validator import OntologyValidator
    from src.service.graph_ingestion_service import GraphIngestionService

    graphiti = MagicMock(); graphiti.add_triplet = AsyncMock()
    ingestion = GraphIngestionService(graphiti, OntologyValidator())
    ingestion._verify_edge_saved = AsyncMock(return_value=True)
    handler = CandidateEvaluationHandler(fetcher=MagicMock(), ingestion_service=ingestion)

    result = await handler.handle_direct(_payload(), org_id="org-a")
    assert result.errors == []
    assert graphiti.add_triplet.await_count == 2


def test_event_router_registers_candidate_evaluation():
    from src.service.event_router import EventRouter
    h = _handler()
    router = EventRouter(feedback_handler=MagicMock(), plan_handler=MagicMock(),
                         decision_handler=MagicMock(), candidate_evaluation=h)
    assert router.get_handler("candidate_evaluation") is h
    assert "candidate_evaluation" in router.supported_events
