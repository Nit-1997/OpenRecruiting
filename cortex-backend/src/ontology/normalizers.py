import json
from pathlib import Path

CATEGORY_NORMALIZATION: dict[str, str] = {
    "behavioural": "behavioral",
    "behaviour": "behavioral",
    "behavior": "behavioral",
    "soft_skills": "behavioral",
    "soft skills": "behavioral",
    "interpersonal": "behavioral",
    "ai": "domain",
    "ml": "domain",
    "machine_learning": "domain",
    "machine learning": "domain",
    "data_science": "domain",
    "data science": "domain",
    "tech": "technical",
    "engineering": "technical",
    "programming": "technical",
    "management": "leadership",
    "people_management": "leadership",
    "people management": "leadership",
}

ROUND_CATEGORY_NORMALIZATION: dict[str, str] = {
    "behavioural": "behavioral",
    "behaviour": "behavioral",
    "technical": "coding",
    "system_design": "design",
    "system design": "design",
    "systems design": "design",
    "cultural": "culture",
    "culture_fit": "culture",
    "culture fit": "culture",
    "phone_screen": "screen",
    "phone screen": "screen",
    "take_home": "assessment",
    "take home": "assessment",
    "takehome": "assessment",
}

_competency_aliases: dict[str, str] | None = None


def _load_competency_aliases() -> dict[str, str]:
    global _competency_aliases
    if _competency_aliases is not None:
        return _competency_aliases
    aliases_path = Path(__file__).parent / "competency_aliases.json"
    if aliases_path.exists():
        with open(aliases_path) as f:
            _competency_aliases = json.load(f)
    else:
        _competency_aliases = {}
    return _competency_aliases


def normalize_category(category: str | None) -> str | None:
    if category is None:
        return None
    lower = category.lower().strip()
    return CATEGORY_NORMALIZATION.get(lower, lower)


def normalize_round_category(category: str | None) -> str | None:
    if category is None:
        return None
    lower = category.lower().strip()
    return ROUND_CATEGORY_NORMALIZATION.get(lower, lower)


def normalize_competency(heading: str) -> str:
    aliases = _load_competency_aliases()
    lower = heading.lower().strip()
    return aliases.get(lower, heading.strip())


def lookup_key(name: str) -> str:
    """Lossless lexical canonicalization key — lowercase + collapse whitespace.

    Used ONLY for entity-resolution lookups. The original display name is preserved
    on the node (first-seen wins) so context is never lost.
    """
    return " ".join(name.strip().lower().split())
