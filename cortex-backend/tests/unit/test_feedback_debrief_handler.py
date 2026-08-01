import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.model.packets import EpisodicMetadata
from src.service.handlers.feedback_debrief_handler import FeedbackDebriefHandler

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


@pytest.fixture
def concepts():
    return load_fixture("extracted_concepts_feedback_debrief.json")


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
        interviewer_ref="interviewer@example.com",
        interviewer_name="Jane Interviewer",
    )


@pytest.fixture
def handler(mock_fetcher, ingestion_service):
    extractor = MagicMock()
    return FeedbackDebriefHandler(mock_fetcher, ingestion_service, extractor)


def test_build_triplets_creates_candidate_exhibits(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    exhibits = [t for t in triplets if t.relation == "EXHIBITS"]
    assert len(exhibits) == 1
    assert exhibits[0].edge_attributes["source"] == "feedback"


def test_build_triplets_creates_interviewer_demonstrates(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    demonstrates = [t for t in triplets if t.relation == "DEMONSTRATES"]
    assert len(demonstrates) == 2
    for t in demonstrates:
        assert t.source_name == "Jane Interviewer"
        assert t.source_id == "interviewer@example.com"


def test_build_triplets_creates_gap_as_experienced_in(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    gaps = [t for t in triplets if t.relation == "EXPERIENCED_IN"]
    assert len(gaps) == 1
    assert gaps[0].target_name == "enterprise B2B"
    assert gaps[0].edge_attributes["depth"] == "exposure"


def test_build_triplets_drops_candidate_trait_misattributed(handler, metadata):
    concepts = {
        "candidate_traits": [
            {"name": "valid", "category": "execution", "polarity": "positive", "evidence": "X", "confidence": "high", "attributed_to": "candidate"},
            {"name": "misattributed", "category": "execution", "polarity": "positive", "evidence": "Y", "confidence": "high", "attributed_to": "interviewer"},
        ],
        "interviewer_traits": [],
        "gaps": [],
    }
    triplets = handler._build_triplets(metadata, concepts)
    exhibits = [t.target_name for t in triplets if t.relation == "EXHIBITS"]
    assert exhibits == ["valid"]


def test_build_triplets_drops_interviewer_trait_misattributed(handler, metadata):
    concepts = {
        "candidate_traits": [],
        "interviewer_traits": [
            {"name": "valid", "category": "execution", "polarity": "positive", "evidence": "X", "pattern_frequency": "consistent", "attributed_to": "interviewer"},
            {"name": "misattributed", "category": "execution", "polarity": "positive", "evidence": "Y", "pattern_frequency": "consistent", "attributed_to": "candidate"},
        ],
        "gaps": [],
    }
    triplets = handler._build_triplets(metadata, concepts)
    demonstrates = [t.target_name for t in triplets if t.relation == "DEMONSTRATES"]
    assert demonstrates == ["valid"]


def test_build_triplets_skips_interviewer_when_no_ref(handler, concepts):
    metadata_no_ref = EpisodicMetadata(
        candidate_round_id="cr-002",
        candidate_id="cand-001",
        candidate_name="Alice Johnson",
        round_id="round-001",
        round_name="System Design",
        round_category="technical",
        requisition_id="req-001",
        role_title="Senior SWE",
        organization_id="org-001",
        interviewer_email=None,
        interviewer_ref=None,
    )
    triplets = handler._build_triplets(metadata_no_ref, concepts)

    demonstrates = [t for t in triplets if t.relation == "DEMONSTRATES"]
    assert len(demonstrates) == 0
