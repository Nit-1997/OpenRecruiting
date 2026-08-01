from src.ontology.normalizers import normalize_category, normalize_round_category, normalize_competency


def test_behavioural_to_behavioral():
    assert normalize_category("behavioural") == "behavioral"
    assert normalize_category("Behavioural") == "behavioral"


def test_ai_to_domain():
    assert normalize_category("AI") == "domain"
    assert normalize_category("ml") == "domain"
    assert normalize_category("machine learning") == "domain"


def test_unknown_category_passthrough():
    assert normalize_category("technical") == "technical"
    assert normalize_category("leadership") == "leadership"


def test_none_category():
    assert normalize_category(None) is None


def test_round_behavioural_to_behavioral():
    assert normalize_round_category("behavioural") == "behavioral"


def test_round_technical_to_coding():
    assert normalize_round_category("technical") == "coding"


def test_round_system_design_to_design():
    assert normalize_round_category("system design") == "design"
    assert normalize_round_category("systems design") == "design"


def test_round_known_category_passthrough():
    assert normalize_round_category("coding") == "coding"
    assert normalize_round_category("design") == "design"


def test_round_none():
    assert normalize_round_category(None) is None


def test_competency_alias():
    assert normalize_competency("problem solving") == "Problem Solving"
    assert normalize_competency("problem-solving") == "Problem Solving"


def test_competency_unknown_passthrough():
    assert normalize_competency("Some Novel Competency") == "Some Novel Competency"


def test_competency_systems_thinking():
    assert normalize_competency("systems thinking") == "System Thinking"


def test_competency_case_insensitive():
    assert normalize_competency("CODE QUALITY") == "Code Quality"
