from pydantic import ValidationError as PydanticValidationError

from src.ontology.entity_types import ENTITY_TYPES
from src.ontology.edge_types import EDGE_TYPE_MAP, EDGE_MODELS


class OntologyValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class OntologyValidator:
    def validate_node(self, entity_type: str, attributes: dict) -> None:
        if entity_type not in ENTITY_TYPES:
            raise OntologyValidationError(
                f"Unknown entity type '{entity_type}'. Valid: {list(ENTITY_TYPES.keys())}"
            )
        model_cls = ENTITY_TYPES[entity_type]
        try:
            model_cls(**attributes)
        except PydanticValidationError as e:
            raise OntologyValidationError(
                f"Invalid attributes for {entity_type}: {e.errors()}"
            )

    def validate_edge(self, source_type: str, target_type: str, relation: str) -> None:
        key = (source_type, target_type)
        if key not in EDGE_TYPE_MAP:
            raise OntologyValidationError(
                f"No relationship defined from '{source_type}' to '{target_type}'"
            )
        allowed = EDGE_TYPE_MAP[key]
        if relation not in allowed:
            raise OntologyValidationError(
                f"Relation '{relation}' not allowed for {source_type}→{target_type}. "
                f"Valid: {allowed}"
            )

    def validate_edge_attributes(self, relation: str, attributes: dict) -> None:
        if relation not in EDGE_MODELS:
            raise OntologyValidationError(f"No edge model for relation '{relation}'")
        model_cls = EDGE_MODELS[relation]
        try:
            model_cls(**attributes)
        except PydanticValidationError as e:
            raise OntologyValidationError(
                f"Invalid edge attributes for {relation}: {e.errors()}"
            )
