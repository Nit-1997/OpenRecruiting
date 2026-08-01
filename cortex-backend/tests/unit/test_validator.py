import pytest

from src.ontology.validator import OntologyValidator, OntologyValidationError


@pytest.fixture
def v():
    return OntologyValidator()


def test_valid_node(v):
    v.validate_node("Skill", {"name": "Python", "category": "technical"})


def test_invalid_entity_type(v):
    with pytest.raises(OntologyValidationError, match="Unknown entity type"):
        v.validate_node("InvalidType", {"name": "test"})


def test_skill_accepts_any_category(v):
    v.validate_node("Skill", {"name": "Python", "category": "any_category"})


def test_valid_edge(v):
    v.validate_edge("Candidate", "Round", "INTERVIEWED_IN")


def test_invalid_edge_pair(v):
    with pytest.raises(OntologyValidationError, match="No relationship defined"):
        v.validate_edge("Skill", "Candidate", "RANDOM")


def test_invalid_relation_for_valid_pair(v):
    with pytest.raises(OntologyValidationError, match="not allowed"):
        v.validate_edge("Candidate", "Round", "HIRED_BY")


def test_valid_edge_attributes(v):
    v.validate_edge_attributes("INTERVIEWED_IN", {"rating": "strong_yes"})


def test_invalid_edge_attributes(v):
    with pytest.raises(OntologyValidationError, match="Invalid edge attributes"):
        v.validate_edge_attributes("INTERVIEWED_IN", {"rating": "invalid_rating"})


def test_valid_competency_node(v):
    v.validate_node("Competency", {"heading": "Problem Solving"})


def test_valid_interviewer_node(v):
    v.validate_node("Interviewer", {"interviewer_ref": "abc123def456"})


def test_valid_location_node(v):
    v.validate_node("Location", {"name": "Remote", "location_type": "remote"})


def test_valid_organization_node(v):
    v.validate_node("Organization", {"name": "Northwind", "organization_ref": "org-uuid", "domain": "northwind.com"})


def test_organization_requires_ref(v):
    with pytest.raises(OntologyValidationError, match="Invalid attributes"):
        v.validate_node("Organization", {"name": "Northwind"})


def test_valid_organization_hosts_requisition_edge(v):
    v.validate_edge("Organization", "Requisition", "HOSTS")


def test_invalid_hosts_pair(v):
    with pytest.raises(OntologyValidationError, match="not allowed"):
        v.validate_edge("Candidate", "Requisition", "HOSTS")


def test_all_edge_type_map_entries_have_models(v):
    from src.ontology.edge_types import EDGE_TYPE_MAP, EDGE_MODELS
    for (src, tgt), relations in EDGE_TYPE_MAP.items():
        for rel in relations:
            assert rel in EDGE_MODELS, f"Missing EDGE_MODELS entry for {rel} ({src}→{tgt})"


def test_concept_entity_types_include_episodic():
    from src.service.graph_ingestion_service import CONCEPT_ENTITY_TYPES
    assert "Company" in CONCEPT_ENTITY_TYPES
    assert "Trait" in CONCEPT_ENTITY_TYPES
    assert "Market" in CONCEPT_ENTITY_TYPES
    assert "Location" in CONCEPT_ENTITY_TYPES
    assert "Candidate" not in CONCEPT_ENTITY_TYPES
    assert "Interviewer" not in CONCEPT_ENTITY_TYPES
