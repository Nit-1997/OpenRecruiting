from unittest.mock import MagicMock

import pytest

from src.model.packets import IntakeMetadata
from src.service.handlers.jd_handler import JDHandler


@pytest.fixture
def extracted():
    return {
        "companies": [{"name": "Acme", "size_signal": "startup", "domain_summary": "AI gateway infrastructure"}],
        "markets": [{"name": "AI infrastructure", "category": "domain"}],
        "requisition_traits": [{"name": "collegial sparring", "category": "cultural", "priority": "must_have", "evidence": "JD: key to the best ideas"}],
        "skills": [],
        "company_traits": [],
        "company_markets": [],
        "company_skills": [],
        "company_locations": [],
    }


@pytest.fixture
def metadata():
    return IntakeMetadata(
        requisition_id="req-001",
        role_title="Senior Backend Engineer",
        organization_id="org-001",
    )


@pytest.fixture
def handler(mock_fetcher, ingestion_service):
    extractor = MagicMock()
    return JDHandler(mock_fetcher, ingestion_service, extractor)


def test_build_triplets_creates_targets_market(handler, metadata, extracted):
    triplets = handler._build_triplets(metadata, extracted)

    targets = [t for t in triplets if t.relation == "TARGETS"]
    assert len(targets) == 1
    assert targets[0].target_name == "AI infrastructure"
    assert targets[0].source_type == "Requisition"


def test_build_triplets_creates_values_trait(handler, metadata, extracted):
    triplets = handler._build_triplets(metadata, extracted)

    values = [t for t in triplets if t.relation == "VALUES"]
    assert len(values) == 1
    assert values[0].target_name == "collegial sparring"
    assert values[0].edge_attributes["evidence"] == "JD: key to the best ideas"


def test_build_triplets_uses_requisition_id(handler, metadata, extracted):
    triplets = handler._build_triplets(metadata, extracted)

    req_triplets = [t for t in triplets if t.source_type == "Requisition"]
    assert all(t.source_id == "req-001" for t in req_triplets)
