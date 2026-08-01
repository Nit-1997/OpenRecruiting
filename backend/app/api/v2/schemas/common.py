"""Shared Literal/enum types used across v2 schemas."""

from typing import Literal


# DB CHECK constraint on candidate_rounds.rating
# (migration 02-interview-plan-requisition.sql line 206). Spec mentions a
# numeric 1–5 scale, but the DB has been a categorical enum since day one;
# DB is source of truth and v1 uses the same set.
RoundRating = Literal["strong_yes", "yes", "maybe", "no", "strong_no"]


# DB CHECK constraint on candidate_feedback.evidence_status
# (migration 02-interview-plan-requisition.sql line 246). The spec narrows to
# flag/unflagged/supported but the DB carries the broader vocabulary; accept
# every DB-valid value.
EvidenceStatus = Literal["supported", "verified", "contradicted", "partial", "none"]
