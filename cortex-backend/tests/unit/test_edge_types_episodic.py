import pytest
from src.ontology.validator import OntologyValidator, OntologyValidationError


@pytest.fixture
def v():
    return OntologyValidator()


def test_candidate_worked_at_company(v):
    v.validate_edge("Candidate", "Company", "WORKED_AT")


def test_worked_at_edge_attributes(v):
    v.validate_edge_attributes("WORKED_AT", {"role_title": "Product Manager", "duration": "5 years", "achievement": "$1M ARR"})


def test_candidate_exhibits_trait(v):
    v.validate_edge("Candidate", "Trait", "EXHIBITS")


def test_exhibits_edge_attributes(v):
    v.validate_edge_attributes("EXHIBITS", {"evidence": "redirected 3 times", "source": "interview", "confidence": "high"})


def test_exhibits_invalid_confidence(v):
    with pytest.raises(OntologyValidationError, match="Invalid edge attributes"):
        v.validate_edge_attributes("EXHIBITS", {"confidence": "super_high"})


def test_candidate_experienced_in_market(v):
    v.validate_edge("Candidate", "Market", "EXPERIENCED_IN")


def test_experienced_in_edge_attributes(v):
    v.validate_edge_attributes("EXPERIENCED_IN", {"depth": "deep", "evidence": "5 years in BFSI", "geographic_scope": "India-only"})


def test_requisition_targets_market(v):
    v.validate_edge("Requisition", "Market", "TARGETS")


def test_requisition_values_trait(v):
    v.validate_edge("Requisition", "Trait", "VALUES")


def test_values_edge_attributes(v):
    v.validate_edge_attributes("VALUES", {"priority": "must_have", "evidence": "HM: higher ownership"})


def test_interviewer_demonstrates_trait(v):
    v.validate_edge("Interviewer", "Trait", "DEMONSTRATES")


def test_demonstrates_edge_attributes(v):
    v.validate_edge_attributes("DEMONSTRATES", {"evidence": "structured 3-part interview", "pattern_frequency": "consistent"})


def test_company_operates_in_market(v):
    v.validate_edge("Company", "Market", "OPERATES_IN")


def test_company_has_culture_trait(v):
    v.validate_edge("Company", "Trait", "HAS_CULTURE")


def test_company_based_in_location(v):
    v.validate_edge("Company", "Location", "BASED_IN")


def test_company_known_for_skill(v):
    v.validate_edge("Company", "Skill", "KNOWN_FOR")


def test_candidate_claimed_skill(v):
    v.validate_edge("Candidate", "Skill", "CLAIMED")


def test_candidate_demonstrated_skill(v):
    v.validate_edge("Candidate", "Skill", "DEMONSTRATED")


def test_candidate_based_in_location(v):
    v.validate_edge("Candidate", "Location", "BASED_IN")


def test_all_episodic_edge_types_have_models():
    from src.ontology.edge_types import EDGE_TYPE_MAP, EDGE_MODELS
    for (src, tgt), relations in EDGE_TYPE_MAP.items():
        for rel in relations:
            assert rel in EDGE_MODELS, f"Missing EDGE_MODELS entry for {rel} ({src}->{tgt})"
