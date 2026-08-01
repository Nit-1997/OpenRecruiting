from pathlib import Path

import pytest
from rdflib import Graph, OWL, RDFS

from src.ontology.entity_types import ENTITY_TYPES
from src.ontology.edge_types import EDGE_TYPE_MAP

TTL_PATH = Path(__file__).parent.parent.parent / "src" / "ontology" / "recruitment.ttl"
ONTOLOGY_NS = "https://openrecruiting.example/ontology/recruitment#"


@pytest.fixture
def ontology_graph():
    g = Graph()
    g.parse(TTL_PATH, format="turtle")
    return g


def test_ttl_classes_match_entity_types(ontology_graph):
    ttl_classes = set()
    for s in ontology_graph.subjects(predicate=None, object=OWL.Class):
        label = ontology_graph.value(s, RDFS.label)
        if label:
            ttl_classes.add(str(label))

    for entity_type in ENTITY_TYPES:
        assert entity_type in ttl_classes, f"ENTITY_TYPES has '{entity_type}' but it's missing from TTL"


def test_ttl_properties_match_edge_type_map(ontology_graph):
    ttl_properties = set()
    for s in ontology_graph.subjects(predicate=None, object=OWL.ObjectProperty):
        label = ontology_graph.value(s, RDFS.label)
        if label:
            ttl_properties.add(str(label))

    all_relations = set()
    for relations in EDGE_TYPE_MAP.values():
        all_relations.update(relations)

    for relation in all_relations:
        assert relation in ttl_properties, f"EDGE_TYPE_MAP has '{relation}' but it's missing from TTL"
