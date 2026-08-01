import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.ontology.validator import OntologyValidator
from src.service.graph_ingestion_service import GraphIngestionService
from src.service.supabase_fetcher import SupabaseFetcher
from src.service.handlers.feedback_handler import FeedbackHandler
from src.service.handlers.plan_handler import PlanHandler
from src.service.handlers.decision_handler import DecisionHandler

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


@pytest.fixture
def validator():
    return OntologyValidator()


@pytest.fixture
def mock_graphiti():
    graphiti = MagicMock()
    graphiti.add_triplet = AsyncMock()
    graphiti.close = AsyncMock()
    return graphiti


@pytest.fixture
def mock_fetcher():
    return MagicMock(spec=SupabaseFetcher)


@pytest.fixture
def ingestion_service(mock_graphiti, validator):
    return GraphIngestionService(mock_graphiti, validator)


@pytest.fixture
def feedback_handler(mock_fetcher, ingestion_service):
    return FeedbackHandler(mock_fetcher, ingestion_service)


@pytest.fixture
def plan_handler(mock_fetcher, ingestion_service):
    return PlanHandler(mock_fetcher, ingestion_service)


@pytest.fixture
def decision_handler(mock_fetcher, ingestion_service):
    return DecisionHandler(mock_fetcher, ingestion_service)
