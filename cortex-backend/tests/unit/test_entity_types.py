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


# The four below are exactly requisitions_status_check in schema.sql. Adding a
# value the DB rejects, or dropping one it stores, parks real events at the
# attempt cap — so these assert the pair stays in lockstep, not just that the
# model works.
@pytest.mark.parametrize(
    "status", ["draft", "intake_pending", "planned", "closed"]
)
def test_requisition_status_accepts_every_db_allowed_value(v, status):
    v.validate_node("Requisition", {"role_title": "Staff AI Engineer", "status": status})


def test_requisition_status_rejects_active(v):
    # 'active' is not in the DB constraint, so no row can ever carry it.
    with pytest.raises(OntologyValidationError, match="Invalid attributes"):
        v.validate_node("Requisition", {"role_title": "X", "status": "active"})


def test_requisition_status_literals_match_db_constraint():
    from typing import get_args
    from src.ontology.entity_types import RequisitionEntity

    annotation = RequisitionEntity.model_fields["status"].annotation
    literal = next(a for a in get_args(annotation) if a is not type(None))
    assert set(get_args(literal)) == {"draft", "intake_pending", "planned", "closed"}
