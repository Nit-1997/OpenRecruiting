"""Quality filters applied at ingestion time to drop low-signal extractions
without losing the rich context on legitimate ones."""
from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

# Tokens that signal a "Market" extraction is actually a skill / trait / capability.
_NON_MARKET_TOKENS = {
    "skills", "skill", "thinking", "knowledge", "experience", "communication",
    "ownership", "mindset", "ability", "abilities", "capability", "capabilities",
    "leadership", "collaboration",
}

_GENERIC_TRAIT_WORDS = {"good", "bad", "great", "okay", "ok", "fine", "average", "smart", "best", "amazing", "nice"}


def is_valid_market(name: str) -> bool:
    if not name or not name.strip():
        return False
    lower = name.strip().lower()
    if lower in _NON_MARKET_TOKENS:
        return False
    tokens = set(lower.replace("-", " ").split())
    return not (tokens & _NON_MARKET_TOKENS)


def is_valid_trait_name(name: str) -> bool:
    """Trait names must be 1-6 words and not generic single words."""
    if not name or not name.strip():
        return False
    stripped = name.strip()
    if len(stripped) < 3:
        return False
    if len(stripped) > 60:
        return False
    words = stripped.split()
    if len(words) > 6:
        return False
    if len(words) == 1 and stripped.lower() in _GENERIC_TRAIT_WORDS:
        return False
    return True


def filter_markets(markets: list[dict]) -> list[dict]:
    kept = []
    for m in markets:
        name = (m or {}).get("name") or ""
        if is_valid_market(name):
            kept.append(m)
        else:
            logger.warning("market_dropped_invalid", name=name)
    return kept


def filter_traits(traits: list[dict], handler: str) -> list[dict]:
    kept = []
    for t in traits:
        name = (t or {}).get("name") or ""
        if is_valid_trait_name(name):
            kept.append(t)
        else:
            logger.warning("trait_dropped_invalid_name", name=name, handler=handler)
    return kept


_CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.3}
_SOURCE_WEIGHT = {
    "interview": 1.0,        # direct candidate utterance
    "feedback": 0.85,        # interviewer's first-hand evaluation
    "question_summary": 0.65,  # LLM-summarized observation
    "intake": 0.7,           # second-hand context
    "summary": 0.55,         # generic summary
}
_PATTERN_WEIGHT = {"consistent": 1.0, "occasional": 0.6, "one_time": 0.4}


def compute_trait_weight(confidence: str | None, source: str | None) -> float:
    c = _CONFIDENCE_WEIGHT.get((confidence or "").lower(), 0.5)
    s = _SOURCE_WEIGHT.get((source or "").lower(), 0.7)
    return round(c * s, 3)


def compute_demonstrates_weight(pattern_frequency: str | None) -> float:
    return _PATTERN_WEIGHT.get((pattern_frequency or "").lower(), 0.6)


_PRIORITY_NORMALIZATION = {
    "must": "must_have",
    "must_have": "must_have",
    "must-have": "must_have",
    "required": "must_have",
    "nice": "nice_to_have",
    "nice_to_have": "nice_to_have",
    "nice-to-have": "nice_to_have",
    "should": "nice_to_have",
    "should_have": "nice_to_have",
    "should-have": "nice_to_have",
    "preferred": "nice_to_have",
    "implicit": "implicit",
    "inferred": "implicit",
}


def normalize_priority(priority: str | None) -> str | None:
    if not priority:
        return None
    return _PRIORITY_NORMALIZATION.get(priority.strip().lower(), None)
