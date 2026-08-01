import pytest
from src.ontology.validator import OntologyValidator, OntologyValidationError


@pytest.fixture
def v():
    return OntologyValidator()


def test_valid_company_entity(v):
    v.validate_node("Company", {"name": "Calendly"})


def test_company_entity_with_size_signal(v):
    v.validate_node("Company", {
        "name": "Calendly",
        "size_signal": "scaleup",
        "domain_summary": "scheduling/productivity SaaS",
    })


def test_company_entity_invalid_size_signal(v):
    with pytest.raises(OntologyValidationError, match="Invalid attributes"):
        v.validate_node("Company", {"name": "X", "size_signal": "giant"})


def test_valid_trait_entity(v):
    v.validate_node("Trait", {"name": "systematic executor"})


def test_trait_entity_with_category_and_polarity(v):
    v.validate_node("Trait", {
        "name": "verbose communicator",
        "category": "communication",
        "polarity": "negative",
    })


def test_trait_entity_accepts_any_category(v):
    v.validate_node("Trait", {"name": "x", "category": "imaginary"})


def test_valid_market_entity(v):
    v.validate_node("Market", {"name": "B2B SaaS"})


def test_market_entity_with_category(v):
    v.validate_node("Market", {"name": "BFSI debt collection", "category": "industry"})


def test_market_entity_accepts_any_category(v):
    v.validate_node("Market", {"name": "x", "category": "fintech_vertical"})
