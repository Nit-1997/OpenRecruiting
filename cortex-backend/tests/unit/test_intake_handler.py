import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.model.packets import IntakeMetadata
from src.service.handlers.intake_handler import IntakeHandler

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


@pytest.fixture
def concepts():
    return load_fixture("extracted_concepts_intake.json")


@pytest.fixture
def metadata():
    return IntakeMetadata(
        requisition_id="req-001",
        role_title="Senior Mobile Engineer",
        organization_id="org-001",
    )


@pytest.fixture
def handler(mock_fetcher, ingestion_service):
    extractor = MagicMock()
    return IntakeHandler(mock_fetcher, ingestion_service, extractor)


def test_build_triplets_creates_targets_market(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    targets = [t for t in triplets if t.relation == "TARGETS"]
    assert len(targets) == 2
    for t in targets:
        assert t.source_type == "Requisition"
        assert t.source_id == "req-001"


def test_build_triplets_creates_values_trait(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    values = [t for t in triplets if t.relation == "VALUES"]
    assert len(values) == 2
    priorities = {t.target_name: t.edge_attributes["priority"] for t in values}
    assert priorities["high ownership"] == "must_have"
    assert priorities["collegial sparring culture"] == "implicit"


def test_build_triplets_creates_company_has_culture(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    culture = [t for t in triplets if t.relation == "HAS_CULTURE"]
    assert len(culture) == 1
    assert culture[0].source_name == "Calendly"
    assert culture[0].edge_attributes["source"] == "intake"


def test_build_triplets_creates_company_operates_in(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    operates = [t for t in triplets if t.relation == "OPERATES_IN"]
    assert len(operates) == 1
    assert operates[0].source_name == "Calendly"
    assert operates[0].target_name == "B2B SaaS"


def test_build_triplets_creates_company_known_for(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    known_for = [t for t in triplets if t.relation == "KNOWN_FOR"]
    assert len(known_for) == 1
    assert known_for[0].source_name == "Calendly"
    assert known_for[0].target_name == "React Native"


def test_build_triplets_creates_company_based_in(handler, metadata, concepts):
    triplets = handler._build_triplets(metadata, concepts)

    based_in = [t for t in triplets if t.relation == "BASED_IN"]
    assert len(based_in) == 1
    assert based_in[0].source_name == "Calendly"
    assert based_in[0].target_name == "Atlanta, GA"


def test_build_triplets_empty_extraction(handler, metadata):
    triplets = handler._build_triplets(metadata, {})
    assert triplets == []
