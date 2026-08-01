from enum import Enum


class EvidenceStatus(str, Enum):
    VERIFIED = "verified"
    CONTRADICTED = "contradicted"
    PARTIAL = "partial"
    NONE = "none"


class RoundRating(str, Enum):
    STRONG_YES = "strong_yes"
    YES = "yes"
    MAYBE = "maybe"
    NO = "no"
    STRONG_NO = "strong_no"
