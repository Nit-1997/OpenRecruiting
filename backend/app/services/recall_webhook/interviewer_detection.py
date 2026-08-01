"""
Synchronous (no-LLM) interviewer email detection from Recall's
`tracked_participants` list.

Used by the recording handler to fill `candidate_rounds.interviewer_email`
when the recruiter didn't supply one at scheduling time. The async,
LLM-based candidate/interviewer disambiguation lives in
`app.services.candidate_detection_service` — this module is the cheap
"host/tenant flag is unambiguous" pass that runs first.

Ported from `backend/v1/app/api/v1/webhooks/recall.py:1158-1211`.
"""

from __future__ import annotations

from app.logging_config import get_logger
from app.utils import names_match


logger = get_logger(__name__)


def is_interviewer(participant: dict) -> bool:
    """An interviewer is anyone Recall marked as host or tenant.
    `is_host` covers Zoom/Meet hosts; `is_tenant` covers Teams employees
    of the inviting org."""
    return bool(participant.get("is_host") or participant.get("is_tenant"))


def detect_interviewer_emails(
    tracked_participants: list[dict],
    candidate_name: str,
) -> list[str]:
    """Detect interviewer emails from Recall participant metadata.

    Priority order:
      1. Any participant flagged `is_host=true` or `is_tenant=true` with
         an email → all of them are interviewers (e.g. panel interview).
      2. Otherwise, exclude the candidate by name. If exactly one
         remaining participant has an email, that's the interviewer.
      3. If ambiguous (multiple candidates with email, or the candidate's
         name didn't match any participant), return an empty list — don't
         guess.

    Returns a deduplicated list of emails, or `[]` when ambiguous.
    """
    if not tracked_participants:
        return []

    # Priority 1: host / tenant flags.
    flagged_emails: list[str] = []
    for p in tracked_participants:
        if is_interviewer(p) and p.get("email"):
            flagged_emails.append(p["email"])
    if flagged_emails:
        deduped = sorted(set(flagged_emails))
        logger.info(
            f"interviewer-detect: {len(deduped)} host/tenant email(s) found"
        )
        return deduped

    # Priority 2: exclude candidate by name.
    candidate_lower = (candidate_name or "").strip().lower()
    if not candidate_lower:
        return []

    candidate_matched = False
    non_candidates: list[dict] = []
    for p in tracked_participants:
        p_name = (p.get("name") or "").strip().lower()
        if not p_name:
            continue
        if names_match(candidate_lower, p_name):
            candidate_matched = True
        else:
            non_candidates.append(p)

    if not candidate_matched:
        # The candidate didn't appear in the participant list at all —
        # we can't safely assume anyone is the interviewer.
        logger.info(
            "interviewer-detect: candidate name didn't match any participant — ambiguous"
        )
        return []

    with_email = [p for p in non_candidates if p.get("email")]
    if len(with_email) == 1:
        email = with_email[0]["email"]
        logger.info(f"interviewer-detect: single non-candidate with email: {email}")
        return [email]

    logger.info(
        f"interviewer-detect: {len(with_email)} non-candidates with email — ambiguous"
    )
    return []
