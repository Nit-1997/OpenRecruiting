"""Candidate profile → the `payload` block of a cortex `/ingest/direct` request.

Pure. The cortex-backend CandidateProfileHandler.build_triplets_from_payload
consumes exactly these keys to attach Candidate→Skill/Company/Market/Location
edges onto the existing Candidate node (keyed by candidate_id). Only the fields
the handler maps are forwarded — not the whole profile blob."""

from __future__ import annotations

import re


def to_cortex_payload(
    *,
    candidate_id: str,
    candidate_name: str | None,
    status: str | None,
    profile: dict,
    requisition_id: str | None = None,
    requisition_title: str | None = None,
    requisition_status: str | None = None,
) -> dict:
    resume = (profile or {}).get("resume") or {}
    ats = (profile or {}).get("ats") or {}
    work_history = [
        {
            "title": w.get("title"),
            "company": w.get("company"),
            "highlights": w.get("highlights") or [],
            "is_current": bool(w.get("is_current")),
        }
        for w in (resume.get("work_history") or [])
        if w.get("company")
    ]
    return {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        "status": status,
        "skills": resume.get("skills") or [],
        "domains": resume.get("domains") or [],
        "work_history": work_history,
        "location": ats.get("location"),
        "seniority": resume.get("seniority"),
        "total_experience_years": resume.get("total_experience_years"),
        # Pipeline membership — Candidate APPLIED_TO Requisition.
        "requisition_id": requisition_id,
        "requisition_title": requisition_title,
        "requisition_status": requisition_status,
        "stage": (ats.get("stage") or {}).get("name"),
        "applied_at": ats.get("applied_at"),
    }


_REC_BY_INT = {4: "strong_yes", 3: "yes", 2: "no", 1: "strong_no"}
# Keyed on the separator-free lowercase form, so "Strong Yes", "strong_yes",
# "StrongYes", and "STRONG-YES" all converge to the same key.
_REC_BY_STR = {
    "strongyes": "strong_yes",
    "yes": "yes",
    "maybe": "maybe",
    "mixed": "maybe",
    "nodecision": "maybe",
    "no": "no",
    "strongno": "strong_no",
    "definitelynot": "strong_no",
    "positive": "yes",
    "negative": "no",
    "neutral": "maybe",
}


def normalize_recommendation(raw) -> str | None:
    """ATS recommendation (or per-attribute rating) → ontology round_rating literal
    (strong_yes..strong_no). Handles Ashby's int 1-4 AND string ValueSelect forms in
    any separator/casing (snake/space/camel). Unrecognized values → None (dropped)."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return _REC_BY_INT.get(int(raw))
    s = str(raw).strip()
    if s.isdigit():                       # Ashby ValueSelect submits string-numeric "4"/"3"/"2"/"1"
        return _REC_BY_INT.get(int(s))
    key = re.sub(r"[^a-z0-9]", "", s.lower())
    return _REC_BY_STR.get(key)


def to_evaluation_payload(*, candidate_id: str, candidate_name: str | None,
                          status: str | None, scorecards: list) -> dict:
    """Build the candidate_evaluation cortex payload from canonical AtsScorecards."""
    evaluations = []
    for sc in scorecards:
        evaluations.append({
            "interviewer_id": sc.interviewer_id,
            "interviewer_name": sc.interviewer_name,
            "recommendation": normalize_recommendation(sc.recommendation),
            "interview_id": sc.interview_id,
            "submitted_at": sc.submitted_at,
            "summary": sc.summary,
            "attributes": [
                {"name": a.name, "rating": normalize_recommendation(a.rating), "note": a.note}
                for a in sc.attributes
                if normalize_recommendation(a.rating) is not None
            ],
        })
    return {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        "status": status,
        "evaluations": evaluations,
    }
