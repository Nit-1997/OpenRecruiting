import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.model.packets import EpisodicMetadata
from src.service.handlers.question_summary_handler import QuestionSummaryHandler

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


@pytest.fixture
def concepts():
    return load_fixture("extracted_concepts_question_summary.json")


@pytest.fixture
def metadata():
    return EpisodicMetadata(
        candidate_round_id="cr-001",
        candidate_id="cand-001",
        candidate_name="Alice Johnson",
        round_id="round-001",
        round_name="System Design",
        round_category="technical",
        requisition_id="req-001",
        role_title="Senior SWE",
        organization_id="org-001",
        interviewer_email="interviewer@example.com",
        interviewer_ref="a1b2c3d4e5f6",
    )


@pytest.fixture
def handler(mock_fetcher, ingestion_service):
    extractor = MagicMock()
    return QuestionSummaryHandler(mock_fetcher, ingestion_service, extractor)


def test_build_triplets_creates_exhibits_edges(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    exhibits = [t for t in triplets if t.relation == "EXHIBITS"]
    assert len(exhibits) == 3
    for t in exhibits:
        assert t.source_type == "Candidate"
        assert t.source_id == "cand-001"
        assert t.edge_attributes["source"] == "question_summary"


def test_build_triplets_creates_skill_edges(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    skill_edges = [t for t in triplets if t.target_type == "Skill"]
    assert len(skill_edges) == 2
    for t in skill_edges:
        assert t.relation == "DEMONSTRATED"


def test_build_triplets_creates_market_edges(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    market_edges = [t for t in triplets if t.relation == "EXPERIENCED_IN"]
    assert len(market_edges) == 1
    assert market_edges[0].target_name == "voice AI"


def test_build_triplets_uses_deterministic_candidate_id(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    candidate_triplets = [t for t in triplets if t.source_type == "Candidate"]
    assert all(t.source_id == "cand-001" for t in candidate_triplets)


def test_build_triplets_empty_extraction(handler, metadata):
    triplets = handler._build_triplets(metadata, {})
    assert triplets == []
