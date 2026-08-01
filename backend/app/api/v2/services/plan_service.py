"""
Shared-plan (rounds + feedback_questions) read + mutation services.

Endpoints owned:
  GET    /roles/{id}/plan                   → get_role_plan
  POST   /roles/{id}/plan/rounds            → add_round
  PUT    /plan/rounds/{round_id}            → update_round
  DELETE /plan/rounds/{round_id}            → delete_round
  POST   /roles/{id}/plan/rounds/reorder    → reorder_rounds
  POST   /plan/rounds/{round_id}/questions  → add_question
  PUT    /plan/questions/{question_id}      → update_question
  DELETE /plan/questions/{question_id}      → delete_question
"""

import re
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from app.api.v2.core.exceptions import (
    ConflictError,
    NotFoundError,
    PreconditionFailedError,
    PreconditionRequiredError,
    ValidationError,
)
from app.api.v2.core.rpc import call_rpc
from app.api.v2.schemas.round import (
    AddQuestionRequest,
    AddRoundRequest,
    ReorderRoundItem,
    UpdateQuestionRequest,
    UpdateRoundRequest,
)
from app.services.supabase import PostgrestError


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

# Screen-naming phrases. If the round name OR category (lowercased) contains one
# of these substrings, the round is an actual recruiter-style screen regardless
# of its position in the plan.
_SCREEN_NAME_KEYWORDS = (
    "recruiter screen",
    "recruiter call",
    "phone screen",
    "phone screening",
    "initial screen",
    "intro call",
    "screening",
)

# The bare word "screen" only counts when it stands as its own token (e.g.
# "Recruiter Screen"), so "Screenwriter Panel" does NOT match.
_SCREEN_WORD_RE = re.compile(r"\bscreen\b")

# Categories whose name alone marks a screen.
_SCREEN_CATEGORIES = {"screening", "recruiter"}

# Conversational categories OpenRecruiting can run as a voice screen — but only when the
# round is the first/early one (round 2 of "behavioral" is a panel, not a screen).
_CONVERSATIONAL_CATEGORIES = {
    "culture",
    "behavioral",
    "screening",
    "recruiter",
    "motivation",
}

# Exercise categories that need live work a voice agent cannot run. These can
# never be a OpenRecruiting screen even when they sit at round 1.
_EXERCISE_CATEGORIES = {
    "coding",
    "design",
    "system_design",
    "case",
    "domain",
    "take_home",
    "technical",
    "assessment",
}


def _is_screen_by_name(category: str, name: str) -> bool:
    """A round is a screen by name when its name or category names a screen."""
    haystack = f"{name} {category}".strip()
    if any(kw in haystack for kw in _SCREEN_NAME_KEYWORDS):
        return True
    if _SCREEN_WORD_RE.search(haystack):
        return True
    return category in _SCREEN_CATEGORIES


def _derive_screenable(stored_flag, category, round_number, name) -> bool:
    """Eligibility for the screening agent, read-side only.

    OpenRecruiting hosts an actual *screen* — a first/early conversational recruiter-style
    round, never a later behavioral/technical panel. A round is screenable when:

      0. an explicit stored True always wins; OR
      1. its name/category names a screen (recruiter/phone/initial screen, intro
         call, screening, or the bare word "screen" as a token); OR
      2. it is the FIRST round (round_number/order_index in {0, 1}) AND its
         category is conversational AND not an exercise category.

    Everything else is False. Never rewrites the DB — this only fills the
    response when the stored flag is unset.
    """
    if stored_flag:
        return True

    cat = (category or "").strip().lower()
    nm = (name or "").strip().lower()

    if _is_screen_by_name(cat, nm):
        return True

    if not cat:
        return False

    is_first = round_number in (0, 1)
    return (
        is_first
        and cat in _CONVERSATIONAL_CATEGORIES
        and cat not in _EXERCISE_CATEGORIES
    )


async def _load_round_for_org(supabase, round_id: UUID, org_id: str) -> dict:
    """Fetch a round + verify its requisition belongs to org_id."""
    result = await (
        supabase.table("rounds")
        .select("*, requisitions(organization_id, deleted_at)")
        .eq("id", str(round_id))
        .is_null("deleted_at")
        .single()
        .execute_async()
    )
    if not result.data:
        raise NotFoundError("Round not found")
    req = result.data.get("requisitions") or {}
    if req.get("organization_id") != org_id or req.get("deleted_at") is not None:
        raise NotFoundError("Round not found")
    return result.data


async def _load_question_for_org(
    supabase, question_id: UUID, org_id: str
) -> dict:
    """Fetch a feedback_question + verify its round → requisition org."""
    result = await (
        supabase.table("feedback_questions")
        .select(
            "*, rounds(id, for_candidate_id, removed_from_plan_at, deleted_at, "
            "requisitions(organization_id, deleted_at))"
        )
        .eq("id", str(question_id))
        .is_null("deleted_at")
        .single()
        .execute_async()
    )
    if not result.data:
        raise NotFoundError("Question not found")
    rnd = result.data.get("rounds") or {}
    if rnd.get("deleted_at") is not None:
        raise NotFoundError("Question not found")
    req = rnd.get("requisitions") or {}
    if req.get("organization_id") != org_id or req.get("deleted_at") is not None:
        raise NotFoundError("Question not found")
    return result.data


def _round_to_response(r: dict) -> dict:
    """Strip embedded join keys before returning a round."""
    return {
        "id": r.get("id"),
        "round_number": r.get("round_number"),
        "name": r.get("name"),
        "category": r.get("category"),
        "duration_minutes": r.get("duration_minutes"),
        "description": r.get("description"),
        "skills": r.get("skills") or [],
        "guidelines": r.get("guidelines") or [],
        "ai_screenable": _derive_screenable(
            r.get("ai_screenable"),
            r.get("category"),
            r.get("round_number"),
            r.get("name"),
        ),
        "ai_screenable_reason": r.get("ai_screenable_reason"),
        "for_candidate_id": r.get("for_candidate_id"),
        "removed_from_plan_at": r.get("removed_from_plan_at"),
        "updated_at": r.get("updated_at"),
    }


def _question_to_response(q: dict) -> dict:
    return {
        "id": q.get("id"),
        "round_id": q.get("round_id"),
        "question_number": q.get("question_number"),
        "heading": q.get("heading"),
        "description": q.get("description"),
    }


def _parse_if_match_iso(value: str) -> datetime:
    """Accept a bare ISO-8601 timestamp. Some clients quote ETags; tolerate
    that. Raises ValidationError if the value can't be parsed."""
    v = value.strip()
    if v.startswith('"') and v.endswith('"'):
        v = v[1:-1]
    if v.startswith("W/"):
        v = v[2:].strip().strip('"')
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValidationError(
            f"Invalid If-Match header (expected ISO-8601 timestamp): {e}"
        )


def _truncate_seconds(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(microsecond=0)


def _feedback_questions_payload(qs) -> Optional[list]:
    if not qs:
        return None
    return [
        {
            "heading": q.heading,
            "description": q.description,
            "question_number": q.question_number,
        }
        for q in qs
    ]


# ---------------------------------------------------------------------------
# GET /roles/{role_id}/plan
# ---------------------------------------------------------------------------


async def get_role_plan(supabase, org_id: str, role_id: UUID) -> dict:
    # Verify the requisition exists for this org. 404 on org mismatch — do
    # not silently return an empty plan, since that would mask an authz bug.
    req_result = await (
        supabase.table("requisitions")
        .select("id")
        .eq("id", str(role_id))
        .eq("organization_id", org_id)
        .is_null("deleted_at")
        .single()
        .execute_async()
    )
    if not req_result.data:
        raise NotFoundError("Role not found")

    rounds_result = await (
        supabase.table("rounds")
        .select(
            "*, feedback_questions(id, question_number, heading, description, deleted_at)"
        )
        .eq("requisition_id", str(role_id))
        .is_null("for_candidate_id")
        .is_null("removed_from_plan_at")
        .is_null("deleted_at")
        .order("round_number")
        .execute_async()
    )
    rounds_raw = rounds_result.data or []

    rounds_out = []
    for r in rounds_raw:
        # PostgREST cannot apply WHERE on embedded relations; filter here.
        questions = [
            {
                "id": q["id"],
                "question_number": q.get("question_number"),
                "heading": q.get("heading"),
                "description": q.get("description"),
            }
            for q in (r.get("feedback_questions") or [])
            if q.get("deleted_at") is None
        ]
        questions.sort(key=lambda q: q.get("question_number") or 0)
        rounds_out.append({
            "id": r["id"],
            "round_number": r.get("round_number"),
            "name": r.get("name"),
            "category": r.get("category"),
            "duration_minutes": r.get("duration_minutes"),
            "description": r.get("description"),
            "skills": r.get("skills") or [],
            "guidelines": r.get("guidelines") or [],
            "ai_screenable": _derive_screenable(
                r.get("ai_screenable"),
                r.get("category"),
                r.get("round_number"),
                r.get("name"),
            ),
            "ai_screenable_reason": r.get("ai_screenable_reason"),
            "feedback_questions": questions,
        })

    return {"rounds": rounds_out}


# ---------------------------------------------------------------------------
# POST /roles/{role_id}/plan/rounds
# ---------------------------------------------------------------------------


async def add_round(
    supabase, org_id: str, role_id: UUID, body: AddRoundRequest
) -> dict:
    data = await call_rpc(
        supabase,
        "add_shared_round",
        {
            "p_req_id": str(role_id),
            "p_name": body.name,
            "p_category": body.category,
            "p_duration_minutes": body.duration_minutes,
            "p_position": body.position,
            "p_description": body.description,
            "p_skills": body.skills,
            "p_guidelines": body.guidelines,
            "p_feedback_questions": _feedback_questions_payload(body.feedback_questions),
            "p_org_id": org_id,
        },
    )
    return data or {}


# ---------------------------------------------------------------------------
# PUT /plan/rounds/{round_id}
# ---------------------------------------------------------------------------


async def update_round(
    supabase, org_id: str, round_id: UUID, body: UpdateRoundRequest
) -> dict:
    rnd = await _load_round_for_org(supabase, round_id, org_id)

    # Custom rounds are mutated via the candidate-journey endpoints.
    if rnd.get("for_candidate_id") is not None:
        raise ValidationError(
            "Custom rounds are edited via the candidate-journey endpoint"
        )
    if rnd.get("removed_from_plan_at") is not None:
        raise ConflictError(
            "REMOVED_FROM_PLAN",
            "Round has been removed from the plan",
        )

    patch: dict = {}
    if body.name is not None:
        patch["name"] = body.name
    if body.category is not None:
        patch["category"] = body.category
    if body.duration_minutes is not None:
        patch["duration_minutes"] = body.duration_minutes
    if body.description is not None:
        patch["description"] = body.description
    if body.skills is not None:
        patch["skills"] = body.skills
    if body.guidelines is not None:
        patch["guidelines"] = body.guidelines

    if not patch:
        # Nothing to do — return the current state instead of issuing an
        # empty PATCH.
        return _round_to_response(rnd)

    patch["updated_at"] = datetime.now(timezone.utc).isoformat()

    update_result = await (
        supabase.table("rounds")
        .update(patch)
        .eq("id", str(round_id))
        .execute_async()
    )
    merged = {**rnd, **(update_result.data or {})}
    return _round_to_response(merged)


# ---------------------------------------------------------------------------
# DELETE /plan/rounds/{round_id}
# ---------------------------------------------------------------------------


async def delete_round(supabase, org_id: str, round_id: UUID) -> dict:
    """Soft-delete a shared round + drop pending CRs (RPC for atomicity).

    Idempotency: a second call where the RPC raises P0001/ALREADY_REMOVED is
    swallowed and the caller sees a 200 with zero pending_crs_deleted —
    matching the legacy behaviour.
    """
    from app.api.v2.core.exceptions import ConflictError as _Conflict

    try:
        data = await call_rpc(
            supabase,
            "delete_shared_round",
            {
                "p_round_id": str(round_id),
                "p_org_id": org_id,
            },
        )
    except _Conflict as conflict:
        if conflict.code == "ALREADY_REMOVED":
            # Idempotent: a second delete returns 200 with prior state.
            return {"deleted_round_id": str(round_id), "pending_crs_deleted": 0}
        raise

    return data or {"deleted_round_id": str(round_id)}


# ---------------------------------------------------------------------------
# POST /roles/{role_id}/plan/rounds/reorder
# ---------------------------------------------------------------------------


async def reorder_rounds(
    supabase,
    org_id: str,
    role_id: UUID,
    items: List[ReorderRoundItem],
    if_match: Optional[str],
) -> dict:
    """Optimistic-concurrency-checked reorder of shared rounds.

    Raises PreconditionRequiredError if the If-Match header is missing,
    PreconditionFailedError if it is stale.
    """
    if if_match is None or not if_match.strip():
        raise PreconditionRequiredError("If-Match header is required for reorder")

    client_ts = _truncate_seconds(_parse_if_match_iso(if_match))

    # Verify the requisition belongs to this org BEFORE comparing timestamps,
    # so we produce 404 instead of 412 for org mismatches.
    req_check = await (
        supabase.table("requisitions")
        .select("id")
        .eq("id", str(role_id))
        .eq("organization_id", org_id)
        .is_null("deleted_at")
        .single()
        .execute_async()
    )
    if not req_check.data:
        raise NotFoundError("Role not found")

    # Read current max(updated_at) over the rounds the reorder will touch.
    current_rounds = await (
        supabase.table("rounds")
        .select("id, updated_at")
        .eq("requisition_id", str(role_id))
        .is_null("for_candidate_id")
        .is_null("removed_from_plan_at")
        .is_null("deleted_at")
        .order("updated_at", desc=True)
        .limit(1)
        .execute_async()
    )
    rows = current_rounds.data or []
    if rows:
        db_ts_raw = rows[0].get("updated_at")
        db_ts = _truncate_seconds(
            datetime.fromisoformat(str(db_ts_raw).replace("Z", "+00:00"))
        )
        if client_ts < db_ts:
            raise PreconditionFailedError("If-Match is stale; reorder rejected")

    payload = [
        {"round_id": str(item.round_id), "round_number": item.round_number}
        for item in items
    ]
    data = await call_rpc(
        supabase,
        "reorder_shared_rounds",
        {
            "p_req_id": str(role_id),
            "p_order": payload,
            "p_org_id": org_id,
        },
    )
    data = data or {}
    return {"rounds": data.get("rounds") or [], "etag": data.get("etag")}


# ---------------------------------------------------------------------------
# POST /plan/rounds/{round_id}/questions
# ---------------------------------------------------------------------------


async def add_question(
    supabase, org_id: str, round_id: UUID, body: AddQuestionRequest
) -> dict:
    rnd = await _load_round_for_org(supabase, round_id, org_id)

    # Custom-round questions are handled via the candidate-journey path.
    if rnd.get("for_candidate_id") is not None:
        raise ValidationError(
            "Custom-round questions use the candidate-journey endpoint"
        )
    if rnd.get("removed_from_plan_at") is not None:
        raise ConflictError(
            "REMOVED_FROM_PLAN",
            "Round has been removed from the plan",
        )

    question_number = body.question_number
    if question_number is None:
        existing = await (
            supabase.table("feedback_questions")
            .select("question_number")
            .eq("round_id", str(round_id))
            .is_null("deleted_at")
            .order("question_number", desc=True)
            .limit(1)
            .execute_async()
        )
        rows = existing.data or []
        question_number = (rows[0].get("question_number") or 0) + 1 if rows else 1

    insert_result = await (
        supabase.table("feedback_questions")
        .insert({
            "round_id": str(round_id),
            "question_number": question_number,
            "heading": body.heading,
            "description": body.description,
        })
        .execute_async()
    )

    row = insert_result.data or {}
    return _question_to_response(row)


# ---------------------------------------------------------------------------
# PUT /plan/questions/{question_id}
# ---------------------------------------------------------------------------


async def update_question(
    supabase, org_id: str, question_id: UUID, body: UpdateQuestionRequest
) -> dict:
    """Save-on-blur update.

    NOTE: partial unique constraint
        idx_unique_question_number (round_id, question_number) WHERE deleted_at IS NULL
    can collide on a direct question_number change. The DB error surfaces as
    a 409 here.
    """
    q = await _load_question_for_org(supabase, question_id, org_id)

    patch: dict = {}
    if body.heading is not None:
        patch["heading"] = body.heading
    if body.description is not None:
        patch["description"] = body.description
    if body.question_number is not None:
        patch["question_number"] = body.question_number

    if not patch:
        return _question_to_response(q)

    patch["updated_at"] = datetime.now(timezone.utc).isoformat()

    try:
        update_result = await (
            supabase.table("feedback_questions")
            .update(patch)
            .eq("id", str(question_id))
            .execute_async()
        )
    except PostgrestError as err:
        # SQLSTATE 23505 == unique_violation. Postgres surfaces this when the
        # partial unique index idx_unique_question_number is hit on a
        # question_number change. Prefer the SQLSTATE check over message
        # string matching — the message text is not contract.
        if err.code == "23505":
            raise ConflictError(
                "DUPLICATE_QUESTION_NUMBER",
                "A question with that question_number already exists in this round",
            )
        raise

    merged = {**q, **(update_result.data or {})}
    return _question_to_response(merged)


# ---------------------------------------------------------------------------
# DELETE /plan/questions/{question_id}
# ---------------------------------------------------------------------------


async def delete_question(supabase, org_id: str, question_id: UUID) -> dict:
    await _load_question_for_org(supabase, question_id, org_id)

    now = datetime.now(timezone.utc).isoformat()
    await (
        supabase.table("feedback_questions")
        .update({"deleted_at": now, "updated_at": now})
        .eq("id", str(question_id))
        .execute_async()
    )
    return {"deleted_question_id": str(question_id)}
