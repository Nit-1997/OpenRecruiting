import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.model.packets import EpisodicMetadata
from src.service.handlers.interview_handler import InterviewHandler

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str):
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


@pytest.fixture
def concepts():
    return load_fixture("extracted_concepts_interview.json")


@pytest.fixture
def metadata():
    return EpisodicMetadata(
        candidate_round_id="cr-001",
        candidate_id="cand-001",
        candidate_name="Pierce",
        round_id="round-001",
        round_name="Product Interview",
        round_category="product",
        requisition_id="req-001",
        role_title="Senior PM",
        organization_id="org-001",
        interviewer_email="nachi@example.com",
        interviewer_ref="nachi@example.com",
        interviewer_name="Sloane Rowanujan",
    )


@pytest.fixture
def handler(mock_fetcher, ingestion_service):
    extractor = MagicMock()
    return InterviewHandler(mock_fetcher, ingestion_service, extractor)


def test_build_triplets_creates_worked_at(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    worked_at = [t for t in triplets if t.relation == "WORKED_AT"]
    assert len(worked_at) == 1
    t = worked_at[0]
    assert t.source_type == "Candidate"
    assert t.target_name == "Sarti"
    assert t.edge_attributes["role_title"] == "Product Manager"
    assert t.edge_attributes["duration"] == "5 years"
    assert t.edge_attributes["achievement"] == "$1M ARR"


def test_build_triplets_creates_experienced_in(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    experienced_in = [t for t in triplets if t.relation == "EXPERIENCED_IN"]
    assert len(experienced_in) == 2
    market_names = {t.target_name for t in experienced_in}
    assert "BFSI debt collection" in market_names
    assert "voice AI" in market_names


def test_build_triplets_creates_skill_edges(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    skill_triplets = [t for t in triplets if t.target_type == "Skill"]
    assert len(skill_triplets) == 2
    relations = {t.target_name: t.relation for t in skill_triplets}
    assert relations["voice AI"] == "DEMONSTRATED"
    assert relations["data modeling"] == "CLAIMED"


def test_build_triplets_creates_candidate_exhibits(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    exhibits = [t for t in triplets if t.relation == "EXHIBITS"]
    assert len(exhibits) == 2
    for t in exhibits:
        assert t.source_type == "Candidate"
        assert t.edge_attributes["source"] == "interview"


def test_build_triplets_creates_interviewer_demonstrates(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    demonstrates = [t for t in triplets if t.relation == "DEMONSTRATES"]
    assert len(demonstrates) == 1
    assert demonstrates[0].source_name == "Sloane Rowanujan"
    assert demonstrates[0].source_id == "nachi@example.com"


def test_build_triplets_creates_company_operates_in(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    operates_in = [t for t in triplets if t.relation == "OPERATES_IN"]
    assert len(operates_in) == 2
    edges = {t.target_name: t for t in operates_in}
    assert "BFSI debt collection" in edges
    assert "voice AI" in edges
    assert edges["BFSI debt collection"].source_name == "Sarti"
    assert edges["BFSI debt collection"].edge_attributes["role"] == "primary"


def test_build_triplets_total_count(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    assert len(triplets) >= 10


def test_build_triplets_drops_candidate_trait_misattributed_to_interviewer(handler, metadata):
    concepts = {
        "candidate_traits": [
            {"name": "valid candidate trait", "category": "execution", "polarity": "positive", "evidence": "did X", "confidence": "high", "attributed_to": "candidate"},
            {"name": "wrongly bucketed", "category": "execution", "polarity": "positive", "evidence": "did Y", "confidence": "high", "attributed_to": "interviewer"},
            {"name": "no attribution", "category": "execution", "polarity": "positive", "evidence": "did Z", "confidence": "high"},
        ],
        "interviewer_traits": [],
    }
    triplets = handler._build_triplets(metadata, concepts)

    exhibits_names = [t.target_name for t in triplets if t.relation == "EXHIBITS"]
    assert exhibits_names == ["valid candidate trait"]


def test_build_triplets_drops_interviewer_trait_misattributed_to_candidate(handler, metadata):
    concepts = {
        "candidate_traits": [],
        "interviewer_traits": [
            {"name": "valid interviewer trait", "category": "execution", "polarity": "positive", "evidence": "asked X", "pattern_frequency": "consistent", "attributed_to": "interviewer"},
            {"name": "wrongly bucketed", "category": "execution", "polarity": "positive", "evidence": "candidate did Y", "pattern_frequency": "consistent", "attributed_to": "candidate"},
        ],
    }
    triplets = handler._build_triplets(metadata, concepts)

    demonstrates_names = [t.target_name for t in triplets if t.relation == "DEMONSTRATES"]
    assert demonstrates_names == ["valid interviewer trait"]
