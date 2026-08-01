"""Tests for CandidateProfileHandler — the `candidate_profile_enriched` direct path.

`build_triplets_from_payload` is pure (no Graphiti/fetcher), so most tests assert
on the emitted Triplets directly. One test pushes them through the REAL
GraphIngestionService + OntologyValidator to prove every edge (and the edge
attributes actually set) passes ontology validation. Also covers null/empty
safety, the existing-Candidate keying, and event_router registration.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.service.graph_ingestion_service import Triplet
from src.service.handlers.candidate_profile_handler import CandidateProfileHandler


def _full_payload() -> dict:
    return {
        "candidate_id": "cand-1",
        "candidate_name": "Jane Doe",
        "status": "active",
        "skills": ["FP&A", "Python"],
        "domains": ["Corporate Finance"],
        "work_history": [
            {
                "title": "Director",
                "company": "Acme",
                "highlights": ["Cut close 8->3 days"],
                "is_current": True,
            }
        ],
        "location": "Sunnyvale, California, US",
        "seniority": "senior",
        "total_experience_years": 12.0,
    }


def _make_handler():
    return CandidateProfileHandler(fetcher=MagicMock(), ingestion_service=MagicMock())


def test_full_payload_emits_expected_relations_and_counts():
    handler = _make_handler()
    triplets = handler.build_triplets_from_payload(_full_payload(), "org-a")

    by_relation: dict[str, list[Triplet]] = {}
    for t in triplets:
        by_relation.setdefault(t.relation, []).append(t)

    # 2 skills + 1 company + 1 domain + 1 location = 5 edges
    assert len(triplets) == 5
    assert len(by_relation["DEMONSTRATED"]) == 2
    assert len(by_relation["WORKED_AT"]) == 1
    assert len(by_relation["EXPERIENCED_IN"]) == 1
    assert len(by_relation["BASED_IN"]) == 1


def test_all_edges_anchor_on_existing_candidate():
    handler = _make_handler()
    triplets = handler.build_triplets_from_payload(_full_payload(), "org-a")

    for t in triplets:
        assert t.source_type == "Candidate"
        assert t.source_id == "cand-1"
        assert t.source_name == "Jane Doe"
        assert t.source_attributes == {
            "name": "Jane Doe",
            "candidate_ref": "cand-1",
            "status": "active",
        }


def test_concept_targets_pass_no_target_id():
    handler = _make_handler()
    triplets = handler.build_triplets_from_payload(_full_payload(), "org-a")
    for t in triplets:
        assert t.target_type in {"Skill", "Company", "Market", "Location"}
        assert t.target_id is None


def test_skill_edge_evidence_is_resume():
    handler = _make_handler()
    triplets = handler.build_triplets_from_payload(_full_payload(), "org-a")
    skills = [t for t in triplets if t.relation == "DEMONSTRATED"]
    assert {t.target_name for t in skills} == {"FP&A", "Python"}
    assert all(t.edge_attributes == {"evidence": "resume"} for t in skills)


def test_worked_at_maps_title_and_highlights_to_edge_attrs():
    handler = _make_handler()
    triplets = handler.build_triplets_from_payload(_full_payload(), "org-a")
    worked = [t for t in triplets if t.relation == "WORKED_AT"]
    assert len(worked) == 1
    assert worked[0].target_name == "Acme"
    # title -> role_title, highlights -> achievement; is_current has no ontology home (dropped)
    assert worked[0].edge_attributes == {
        "role_title": "Director",
        "achievement": "Cut close 8->3 days",
    }
    assert "is_current" not in worked[0].edge_attributes


def test_experienced_in_and_based_in_targets():
    handler = _make_handler()
    triplets = handler.build_triplets_from_payload(_full_payload(), "org-a")
    market = [t for t in triplets if t.relation == "EXPERIENCED_IN"]
    location = [t for t in triplets if t.relation == "BASED_IN"]
    assert [t.target_name for t in market] == ["Corporate Finance"]
    assert [t.target_name for t in location] == ["Sunnyvale, California, US"]


def _payload_with_requisition() -> dict:
    p = _full_payload()
    p.update({
        "requisition_id": "req-1",
        "requisition_title": "Senior Software Engineer",
        "requisition_status": "intake_pending",
        "stage": "Assessment",
        "applied_at": "2026-06-12T20:33:28Z",
    })
    return p


def test_applied_to_requisition_edge_when_requisition_present():
    handler = _make_handler()
    triplets = handler.build_triplets_from_payload(_payload_with_requisition(), "org-a")
    applied = [t for t in triplets if t.relation == "APPLIED_TO"]
    assert len(applied) == 1
    edge = applied[0]
    assert edge.source_type == "Candidate" and edge.source_id == "cand-1"
    assert edge.target_type == "Requisition"
    assert edge.target_id == "req-1"  # keyed by real id — NOT a concept target
    assert edge.target_name == "Senior Software Engineer"
    assert edge.edge_attributes == {
        "stage": "Assessment",
        "status": "active",
        "applied_at": "2026-06-12T20:33:28Z",
        "source": "ats_sync",
    }
    assert len(triplets) == 6  # the original 5 + APPLIED_TO


def test_no_applied_to_when_requisition_absent():
    handler = _make_handler()
    triplets = handler.build_triplets_from_payload(_full_payload(), "org-a")
    assert not any(t.relation == "APPLIED_TO" for t in triplets)


@pytest.mark.asyncio
async def test_applied_to_validates_against_ontology():
    from src.ontology.validator import OntologyValidator
    from src.service.graph_ingestion_service import GraphIngestionService

    graphiti = MagicMock()
    graphiti.add_triplet = AsyncMock()
    real_ingestion = GraphIngestionService(graphiti, OntologyValidator())
    real_ingestion._verify_edge_saved = AsyncMock(return_value=True)

    handler = CandidateProfileHandler(fetcher=MagicMock(), ingestion_service=real_ingestion)
    result = await handler.handle_direct(_payload_with_requisition(), org_id="org-a")

    assert result.errors == []
    assert result.edges_created == 6
    assert graphiti.add_triplet.await_count == 6


def test_empty_payload_yields_just_candidate_no_edges():
    handler = _make_handler()
    triplets = handler.build_triplets_from_payload(
        {"candidate_id": "cand-2", "candidate_name": "John Roe"}, "org-a"
    )
    assert triplets == []


def test_missing_candidate_id_yields_empty():
    handler = _make_handler()
    triplets = handler.build_triplets_from_payload({"candidate_name": "Nobody"}, "org-a")
    assert triplets == []


def test_work_history_entry_without_company_is_skipped():
    handler = _make_handler()
    payload = {
        "candidate_id": "cand-3",
        "candidate_name": "Skip Co",
        "work_history": [
            {"title": "Freelancer", "company": "", "highlights": ["x"]},
            {"title": "Lead", "company": "Globex"},
        ],
    }
    triplets = handler.build_triplets_from_payload(payload, "org-a")
    worked = [t for t in triplets if t.relation == "WORKED_AT"]
    assert [t.target_name for t in worked] == ["Globex"]


def test_worked_at_with_no_title_or_highlights_has_empty_edge_attrs():
    handler = _make_handler()
    payload = {
        "candidate_id": "cand-4",
        "candidate_name": "Bare Co",
        "work_history": [{"company": "Initech"}],
    }
    triplets = handler.build_triplets_from_payload(payload, "org-a")
    worked = [t for t in triplets if t.relation == "WORKED_AT"]
    assert len(worked) == 1
    assert worked[0].edge_attributes == {}


@pytest.mark.asyncio
async def test_triplets_validate_against_ontology():
    """Every emitted edge + edge attribute must pass the REAL ontology validator."""
    from src.ontology.validator import OntologyValidator
    from src.service.graph_ingestion_service import GraphIngestionService

    graphiti = MagicMock()
    graphiti.add_triplet = AsyncMock()
    real_ingestion = GraphIngestionService(graphiti, OntologyValidator())
    # _verify_edge_saved would hit the Neo4j driver — stub it to confirm the save.
    real_ingestion._verify_edge_saved = AsyncMock(return_value=True)

    handler = CandidateProfileHandler(fetcher=MagicMock(), ingestion_service=real_ingestion)
    result = await handler.handle_direct(_full_payload(), org_id="org-a")

    assert result.errors == []
    assert result.edges_created == 5
    assert graphiti.add_triplet.await_count == 5


def test_event_router_registers_candidate_profile_enriched():
    from src.service.event_router import EventRouter

    handler = _make_handler()
    router = EventRouter(
        feedback_handler=MagicMock(),
        plan_handler=MagicMock(),
        decision_handler=MagicMock(),
        candidate_profile_enriched=handler,
    )
    assert router.get_handler("candidate_profile_enriched") is handler
    assert "candidate_profile_enriched" in router.supported_events
