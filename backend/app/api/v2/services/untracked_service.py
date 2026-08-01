"""Untracked-interview service (v2).

Listing + management of untracked-but-detected interviews captured by
Calendar Intelligence. The read path mirrors the v1 query shape from
`backend/v1/app/services/untracked_import_service.py`; the mutation
path implements the 3-button product surface in the FE roles rail:

    - Import as a New Role  → FE routes to /intake (no backend mutation)
    - Link to Existing      → POST .../link-to-existing  (this module)
    - Not an Interview      → POST .../mark-not-interview (this module)

Org isolation: every binding includes `organization_id = org_id` either
directly or via the parent requisition row, per CLAUDE.md "service-role
bypasses RLS — org scope must be in every WHERE clause".

The full v1 import flow copies transcript + recording + feedback into the
target round and triggers re-processing. This v2 surface writes the
identity rows synchronously (untracked_interview_imports + candidate +
candidate_round) and relies on the existing v1 transcript-copy path for
media-level reprocessing — keep the heavy v1 service as the source of
truth; v2 only exposes a smaller, FE-shaped surface on top of it.
"""

from datetime import datetime
from typing import Any, Optional

from app.logging_config import get_logger
from app.services._supabase_rows import is_unique_violation

logger = get_logger(__name__)


# Keep in sync with v1 `GENERIC_TEMPLATE_CONFIG["template_key"]`
# (backend/v1/app/services/untracked_capture_service.py:15). The
# system template that captures generic untracked interviews is bound
# per-org via `org_generic_template_bindings.template_key`. The literal
# is intentionally SHOUTY_SNAKE — that's the value v1 inserts and the
# value already living in production rows.
GENERIC_TEMPLATE_KEY = "GLOBAL_UNTRACKED_INTERVIEW_V1"


async def list_untracked(
    supabase,
    org_id: str,
    *,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[dict], int]:
    """Return one page of available/imported untracked interviews for an org.

    Read-only. Filters dismissed rows out at the application level (the v1
    surface lets clients query by view; v2 FE always wants the full active
    set — `view='available' | 'imported'` is collapsed here for simplicity).

    Pagination is applied AFTER the v1-shaped join + sort because the source
    rows come from multiple tables that PostgREST can't paginate together
    server-side. Total reflects the full set; the returned list is the slice.
    """
    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)

    binding_result = await (
        supabase.table("org_generic_template_bindings")
        .select("materialized_requisition_id, template_key")
        .eq("organization_id", org_id)
        .eq("template_key", GENERIC_TEMPLATE_KEY)
        .limit(1)
        .execute_async()
    )
    binding = _first(binding_result.data)
    if not binding:
        return ([], 0)

    generic_requisition_id = str(binding["materialized_requisition_id"])

    # Candidates under the org's generic-template requisition.
    candidates_result = await (
        supabase.table("candidates")
        .select("id, requisition_id, name, email")
        .eq("requisition_id", generic_requisition_id)
        .is_("deleted_at", "null")
        .execute_async()
    )
    candidates = candidates_result.data or []
    if not candidates:
        return ([], 0)

    cand_by_id = {str(c["id"]): c for c in candidates}
    cand_ids = list(cand_by_id.keys())

    # The captured candidate_rounds — one per detected calendar event.
    rounds_result = await (
        supabase.table("candidate_rounds")
        .select(
            "id, candidate_id, origin_detection_id, interviewer_email, "
            "status, scheduled_at, recording_url"
        )
        .in_("candidate_id", cand_ids)
        .eq("source_type", "untracked_generic")
        .neq("status", "cancelled")
        .execute_async()
    )
    rounds = rounds_result.data or []
    if not rounds:
        return ([], 0)

    # Detections carry the human-readable event title + start time.
    detection_ids = [
        str(r["origin_detection_id"])
        for r in rounds
        if r.get("origin_detection_id")
    ]
    detections_by_id: dict[str, dict] = {}
    if detection_ids:
        detections_result = await (
            supabase.table("calendar_event_detections")
            .select("id, event_title, event_start, event_end")
            .in_("id", detection_ids)
            .execute_async()
        )
        detections_by_id = {
            str(d["id"]): d for d in (detections_result.data or [])
        }

    # Latest import row per source round — drives `status` +
    # `imported_requisition_id` + `imported_candidate_id`.
    source_round_ids = [str(r["id"]) for r in rounds if r.get("id")]
    # The ACTIVE (honored) attempt drives the row's status. superseded_at IS NULL
    # is the live association; an undone link is superseded, so the source has no
    # active import and correctly shows as "available" again.
    active_import_by_source: dict[str, dict] = {}
    if source_round_ids:
        imports_result = await (
            supabase.table("untracked_interview_imports")
            .select(
                "source_generic_candidate_round_id, target_requisition_id, "
                "target_candidate_id, import_status, superseded_at, created_at"
            )
            .in_("source_generic_candidate_round_id", source_round_ids)
            .is_("superseded_at", "null")
            .execute_async()
        )
        for row in (imports_result.data or []):
            sid = str(row.get("source_generic_candidate_round_id") or "")
            if not sid:
                continue
            existing = active_import_by_source.get(sid)
            ts = str(row.get("created_at") or "")
            if not existing or ts > str(existing.get("created_at") or ""):
                active_import_by_source[sid] = row

    rows_out: list[dict] = []
    for r in rounds:
        sid = str(r.get("id") or "")
        if not sid:
            continue
        cand = cand_by_id.get(str(r.get("candidate_id") or ""))
        if not cand:
            continue
        det = detections_by_id.get(str(r.get("origin_detection_id") or ""), {})
        event_start = det.get("event_start") or r.get("scheduled_at")
        if not event_start:
            # Without an event timestamp, the FE can't render the card;
            # skip rather than emit a row with `null` event_start (the
            # schema/FE type is non-optional).
            continue

        imp = active_import_by_source.get(sid)
        if imp:
            # The DB import_status is the v1 copy-lifecycle value
            # (copied / copied_pending_scorecard / reprocessed / ...). The FE
            # only models available | imported | dismissed, so any non-dismissed
            # import — the interview is attached to a real round — maps to
            # "imported".
            raw_status = str(imp.get("import_status") or "")
            status = "dismissed" if raw_status == "dismissed" else "imported"
            imported_req = imp.get("target_requisition_id")
            imported_cand = imp.get("target_candidate_id")
        else:
            status = "available"
            imported_req = None
            imported_cand = None

        # Dismissed rows are filtered out (matches v1 list_org_untracked
        # semantics — dismissed is a terminal state hidden from the rail).
        if status == "dismissed":
            continue

        rows_out.append(
            {
                "id": sid,
                "candidate_name": cand.get("name") or "Unknown Candidate",
                "candidate_email": cand.get("email") or "",
                "event_title": det.get("event_title") or "Interview",
                "event_start": event_start,
                "event_duration_minutes": _duration_minutes(
                    det.get("event_start"), det.get("event_end")
                ),
                "interviewer_email": r.get("interviewer_email") or "",
                "recording_url": r.get("recording_url"),
                "status": status,
                "imported_candidate_id": imported_cand,
                "imported_requisition_id": imported_req,
                # Source-side identity — see schema for why the FE needs it.
                "source_candidate_id": cand.get("id"),
                "source_requisition_id": generic_requisition_id,
                "detected_at": event_start,
            }
        )

    rows_out.sort(key=lambda x: str(x.get("event_start") or ""), reverse=True)
    total = len(rows_out)
    start = (page - 1) * page_size
    end = start + page_size
    return (rows_out[start:end], total)


def _first(data: Any) -> Optional[dict]:
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        return data
    return None


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _duration_minutes(start: Any, end: Any) -> int:
    """Minutes between two ISO timestamps. `calendar_event_detections` stores
    `event_start`/`event_end` (no duration column), so derive it here. Returns
    0 when either bound is missing or unparseable."""
    if not start or not end:
        return 0
    try:
        delta = datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(start))
    except (TypeError, ValueError):
        return 0
    return max(0, int(delta.total_seconds() // 60))


class UntrackedMutationError(Exception):
    """Raised by the link/dismiss flows; carries an HTTP status hint."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


async def _load_source_round(supabase, source_candidate_round_id: str) -> dict:
    """Fetch the source candidate_round (under the org's generic req) and
    join enough context to drive the link/dismiss/packet flows. Org
    isolation is enforced at the next step via the parent requisition
    lookup. The SELECT carries every column the packet builder reads
    (round_id, summary, rating, question_summaries, scorecard_transcript)
    so a single fetch covers all three call sites.
    """
    cr_result = await (
        supabase.table("candidate_rounds")
        .select(
            "id, candidate_id, round_id, origin_detection_id, scheduled_at, "
            "completed_at, interviewer_email, meeting_url, recording_url, "
            "transcript_url, source_type, status, summary, rating, "
            "question_summaries, scorecard_transcript, processing_status"
        )
        .eq("id", source_candidate_round_id)
        .limit(1)
        .execute_async()
    )
    row = _first(cr_result.data)
    if not row:
        raise UntrackedMutationError(404, "Untracked interview not found")
    if str(row.get("source_type") or "") != "untracked_generic":
        raise UntrackedMutationError(400, "Not an untracked interview")
    return row


async def _load_candidate(supabase, candidate_id: str) -> dict:
    result = await (
        supabase.table("candidates")
        .select("id, requisition_id, name, email, phone, resume_url")
        .eq("id", candidate_id)
        .limit(1)
        .execute_async()
    )
    row = _first(result.data)
    if not row:
        raise UntrackedMutationError(404, "Source candidate not found")
    return row


async def _assert_source_in_org(supabase, source_req_id: str, org_id: str) -> None:
    """Confirm the source candidate's requisition belongs to the caller's
    org. Generic-template reqs are flagged with `is_system_template=true`;
    we additionally require organization_id to match.
    """
    result = await (
        supabase.table("requisitions")
        .select("id, organization_id, is_system_template")
        .eq("id", source_req_id)
        .limit(1)
        .execute_async()
    )
    row = _first(result.data)
    if not row or str(row.get("organization_id") or "") != str(org_id):
        raise UntrackedMutationError(403, "Forbidden")
    if not bool(row.get("is_system_template")):
        raise UntrackedMutationError(400, "Invalid source interview")


async def _load_target_round(
    supabase, requisition_id: str, target_round_id: Optional[str], org_id: str
) -> dict:
    """Resolve the target round. If target_round_id is None, pick the
    requisition's first active shared round (matches the FE flow which
    doesn't expose round selection at the link step).
    """
    req_result = await (
        supabase.table("requisitions")
        .select("id, organization_id, is_system_template")
        .eq("id", requisition_id)
        .limit(1)
        .execute_async()
    )
    req = _first(req_result.data)
    if not req or str(req.get("organization_id") or "") != str(org_id):
        raise UntrackedMutationError(404, "Requisition not found")
    if bool(req.get("is_system_template")):
        raise UntrackedMutationError(400, "Cannot link into a system requisition")

    if target_round_id:
        rr = await (
            supabase.table("rounds")
            .select("id, requisition_id, round_number")
            .eq("id", target_round_id)
            .eq("requisition_id", requisition_id)
            .is_("deleted_at", "null")
            .limit(1)
            .execute_async()
        )
        row = _first(rr.data)
        if not row:
            raise UntrackedMutationError(404, "Round not found in this requisition")
        return row

    rounds_result = await (
        supabase.table("rounds")
        .select("id, requisition_id, round_number")
        .eq("requisition_id", requisition_id)
        .is_("deleted_at", "null")
        .order("round_number", desc=False)
        .limit(1)
        .execute_async()
    )
    row = _first(rounds_result.data)
    if not row:
        raise UntrackedMutationError(
            400, "This role has no active rounds to import into."
        )
    return row


async def _imports_for_source(
    supabase, source_candidate_round_id: str
) -> list[dict]:
    """All import rows for one untracked interview, newest first.

    UNTRACKED-MA: an untracked interview accumulates multiple association
    attempts over time. Callers derive the active attempt (superseded_at IS
    NULL) and any exact-target match in Python from this single fetch, so the
    multi-attempt branching costs one query, not several.
    """
    result = await (
        supabase.table("untracked_interview_imports")
        .select(
            "id, target_requisition_id, target_round_id, target_candidate_id, "
            "target_candidate_round_id, import_status, superseded_at, created_at"
        )
        .eq("source_generic_candidate_round_id", source_candidate_round_id)
        .order("created_at", desc=True)
        .execute_async()
    )
    return result.data or []


def _active_import(imports: list[dict]) -> Optional[dict]:
    """The honored attempt: newest non-dismissed row with superseded_at NULL.

    A dismissed row is terminal (mark_not_interview) and never an active
    attempt; it is excluded so it neither blocks nor is superseded by a link.
    `imports` is already newest-first.
    """
    for row in imports:
        if str(row.get("import_status") or "") == "dismissed":
            continue
        if row.get("superseded_at") is None:
            return row
    return None


def _exact_target_import(
    imports: list[dict],
    *,
    target_requisition_id: str,
    target_round_id: str,
) -> Optional[dict]:
    """The newest non-dismissed import for the EXACT (source, req, round)
    triple — the row guarded by uq_import_source_target. Used to reactivate a
    prior attempt on reassign-back instead of inserting a colliding row.
    """
    for row in imports:
        if str(row.get("import_status") or "") == "dismissed":
            continue
        if (
            str(row.get("target_requisition_id") or "") == str(target_requisition_id)
            and str(row.get("target_round_id") or "") == str(target_round_id)
        ):
            return row
    return None


async def _resolve_target_candidate(
    supabase,
    *,
    target_requisition_id: str,
    source_candidate: dict,
) -> tuple[str, bool]:
    """Reuse an existing candidate with the same email in the target req
    if present; otherwise create one. Returns `(candidate_id, created)`.
    """
    email = str(source_candidate.get("email") or "").strip().lower()
    if email:
        # Case-insensitive EXACT match. This client's .ilike wraps the pattern as
        # *pattern* (a SUBSTRING match), and .eq is case-SENSITIVE — neither is
        # safe alone (substring attaches to the wrong person, e.g. sam@x vs
        # samuel@x; eq misses a mixed-case stored email). So narrow with ilike,
        # then confirm an exact lowercased equality in Python.
        existing_result = await (
            supabase.table("candidates")
            .select("id, email")
            .eq("requisition_id", target_requisition_id)
            .ilike("email", email)
            .is_("deleted_at", "null")
            .execute_async()
        )
        existing = next(
            (
                c
                for c in (existing_result.data or [])
                if str(c.get("email") or "").strip().lower() == email
            ),
            None,
        )
        if existing:
            return (str(existing["id"]), False)

    insert_result = await (
        supabase.table("candidates")
        .insert(
            {
                "requisition_id": target_requisition_id,
                "name": str(source_candidate.get("name") or "Untracked candidate"),
                # Store the normalized (lowercased/stripped) email so the
                # .eq() reuse lookup above matches it on a later reassociation.
                "email": email or str(source_candidate.get("email") or ""),
                "phone": source_candidate.get("phone"),
                "resume_url": source_candidate.get("resume_url"),
                "status": "active",
            }
        )
        .execute_async()
    )
    new_row = _first(insert_result.data)
    if not new_row:
        raise UntrackedMutationError(500, "Failed to create candidate in target role")
    return (str(new_row["id"]), True)


async def _existing_target_round(
    supabase, candidate_id: str, round_id: str
) -> Optional[dict]:
    """The target candidate's existing non-generic round for `round_id`, if any.

    A candidate already in a pipeline holds one such row per shared round (the
    partial unique index idx_candidate_rounds_unique_non_generic guarantees at
    most one), so the link flow attaches the interview to it in place rather
    than inserting a colliding duplicate. Returns None when the candidate has no
    round for `round_id` (a genuinely new candidate), in which case we insert.

    Selects every field the link overwrites so the caller can snapshot the prior
    state and restore it if a later step fails (the round is a real pipeline row
    — a half-applied update must never be left behind).
    """
    result = await (
        supabase.table("candidate_rounds")
        .select(
            "id, status, source_type, origin_candidate_round_id, "
            "origin_detection_id, scheduled_at, completed_at, interviewer_email, "
            "interviewer_name, meeting_url, recording_url, transcript_url, "
            "rating, summary, question_summaries, scorecard_status, processing_status"
        )
        .eq("candidate_id", candidate_id)
        .eq("round_id", round_id)
        .neq("source_type", "untracked_generic")
        .limit(1)
        .execute_async()
    )
    return _first(result.data)


# Fields the link flow overwrites on a candidate's existing round — the exact
# set snapshotted by _existing_target_round and rolled back by
# _restore_round_state, so the two stay in lock-step.
_ROUND_OVERWRITE_FIELDS = (
    "status",
    "source_type",
    "origin_candidate_round_id",
    "origin_detection_id",
    "scheduled_at",
    "completed_at",
    "interviewer_email",
    "interviewer_name",
    "meeting_url",
    "recording_url",
    "transcript_url",
)


# Everything a merge could change on the target round, snapshotted onto the
# import (prior_round_snapshot) so undo_untracked_link can fully restore it —
# the overwrite fields PLUS the scorecard columns (which a later "process"/
# feedback run overwrites).
_ROUND_SNAPSHOT_FIELDS = _ROUND_OVERWRITE_FIELDS + (
    "rating",
    "summary",
    "question_summaries",
    "scorecard_status",
    "processing_status",
)


async def _load_round_feedback(supabase, candidate_round_id: str) -> list[dict]:
    """The candidate_feedback rows for a round, snapshotted at merge time so undo
    restores the prior scorecard exactly."""
    result = await (
        supabase.table("candidate_feedback")
        .select(
            "id, feedback_question_id, feedback_text, evidence, "
            "evidence_status, source, created_at"
        )
        .eq("candidate_round_id", candidate_round_id)
        .execute_async()
    )
    return result.data or []


async def _restore_round_state(supabase, prior_round: dict) -> None:
    """Revert a candidate's existing round to its pre-link state.

    Called when the import tracker insert fails AFTER we updated the round in
    place — without this the candidate is left holding a phantom completed
    untracked-copy round with no import record. Best-effort, same swallow
    contract as the other compensation helpers.
    """
    fields = {key: prior_round.get(key) for key in _ROUND_OVERWRITE_FIELDS}
    try:
        await (
            supabase.table("candidate_rounds")
            .update({**fields, "updated_at": _now_iso()})
            .eq("id", str(prior_round["id"]))
            .execute_async()
        )
    except Exception as exc:
        logger.error(
            "v2 untracked-link: failed to restore round after import insert "
            "failure cr_id=%s err=%s",
            str(prior_round.get("id")),
            str(exc),
        )


# Columns copied from the source interview transcript onto the target round.
# feedback_transcript is intentionally NOT copied — an untracked interview has an
# interview transcript, not interviewer feedback; the Lambda's segment path scores
# the interview against the target round's scorecard.
_TRANSCRIPT_COPY_FIELDS = (
    "segments",
    "full_text",
    "raw_transcript_url",
    "word_count",
    "duration_seconds",
    "language",
    "provider",
    "recall_transcript_id",
    "participant_metadata",
)


async def _copy_interview_transcript(
    supabase, source_candidate_round_id: str, target_candidate_round_id: str
) -> bool:
    """Copy the source interview's transcript row onto the target round.

    The feedback Lambda reads `transcripts` by candidate_round_id, so the target
    round needs its own transcript row to be scoreable. Upserts (update if the
    target already has a row, else insert). Returns True if a source transcript
    existed and was copied.
    """
    src_result = await (
        supabase.table("transcripts")
        .select(", ".join(_TRANSCRIPT_COPY_FIELDS))
        .eq("candidate_round_id", source_candidate_round_id)
        .limit(1)
        .execute_async()
    )
    src_row = _first(src_result.data)
    if not src_row:
        return False

    payload = {key: src_row.get(key) for key in _TRANSCRIPT_COPY_FIELDS}
    payload["candidate_round_id"] = target_candidate_round_id

    existing_result = await (
        supabase.table("transcripts")
        .select("id")
        .eq("candidate_round_id", target_candidate_round_id)
        .limit(1)
        .execute_async()
    )
    existing_row = _first(existing_result.data)
    if existing_row:
        await (
            supabase.table("transcripts")
            .update(payload)
            .eq("id", str(existing_row["id"]))
            .execute_async()
        )
    else:
        await supabase.table("transcripts").insert(payload).execute_async()
    return True


async def _cancel_round_best_effort(supabase, candidate_round_id: Optional[str]) -> None:
    """Cancel a candidate_round we are stepping away from.

    Two callers:
      - the import-race loser cancels the orphan round it just created;
      - a forward reassign cancels the PRIOR active import's round (removing the
        mis-assignment from the wrong candidate's active pipeline).
    In both cases we mark it 'cancelled' (NEVER delete) so no duplicate active
    round survives and the prior attempt's feedback rows stay restorable. A
    failure here is logged, not propagated — the real outcome is the caller's.
    """
    if not candidate_round_id:
        return
    try:
        await (
            supabase.table("candidate_rounds")
            .update({"status": "cancelled", "updated_at": _now_iso()})
            .eq("id", candidate_round_id)
            .execute_async()
        )
    except Exception as exc:
        logger.error(
            "v2 untracked-link: failed to cancel round cr_id=%s err=%s",
            candidate_round_id,
            str(exc),
        )


async def _supersede_prior_active(supabase, prior_active: dict) -> None:
    """UNTRACKED-MA forward reassign: retire the source's current active import.

    Marks the prior active import `superseded_at = now()` (kept history) and
    cancels its candidate_round (feedback rows are NOT touched, so the attempt
    is restorable). No-op when there is no prior active attempt.
    """
    await (
        supabase.table("untracked_interview_imports")
        .update({"superseded_at": _now_iso(), "updated_at": _now_iso()})
        .eq("id", str(prior_active["id"]))
        .execute_async()
    )
    await _cancel_round_best_effort(
        supabase, prior_active.get("target_candidate_round_id")
    )


async def _restore_prior_active(supabase, prior_active: dict) -> None:
    """Inverse of `_supersede_prior_active`.

    Re-honors a prior attempt we already superseded when creating the NEW attempt
    then fails (e.g. the target candidate already holds this round -> 23505), so
    the source is never left with ZERO active attempts. Round restore is
    best-effort (mirrors the cancel contract).
    """
    await (
        supabase.table("untracked_interview_imports")
        .update({"superseded_at": None, "updated_at": _now_iso()})
        .eq("id", str(prior_active["id"]))
        .execute_async()
    )
    restored_cr_id = prior_active.get("target_candidate_round_id")
    if restored_cr_id:
        try:
            await (
                supabase.table("candidate_rounds")
                .update({"status": "completed", "updated_at": _now_iso()})
                .eq("id", str(restored_cr_id))
                .execute_async()
            )
        except Exception as exc:
            logger.error(
                "v2 untracked-link: failed to restore prior round after conflict "
                "cr_id=%s err=%s",
                str(restored_cr_id),
                str(exc),
            )


async def link_to_existing(
    supabase,
    *,
    org_id: str,
    source_candidate_round_id: str,
    target_requisition_id: str,
    target_round_id: Optional[str],
    mode: str = "new_candidate",
    target_candidate_id: Optional[str] = None,
    imported_by_user_id: Optional[str],
    interviewer_email: Optional[str] = None,
    interviewer_name: Optional[str] = None,
    scheduled_at: Optional[str] = None,
) -> dict:
    """Link an untracked interview into an existing role (re)association.

    UNTRACKED-MA: an untracked interview is flexibly re-associable. Linking it
    to a NEW target supersedes the source's current active attempt (its prior
    round is cancelled but its feedback is KEPT/restorable) and creates a fresh
    honored attempt. Linking back to a PRIOR target reactivates that superseded
    attempt instead of inserting (avoids the uq_import_source_target collision).
    Linking to the SAME active target is an idempotent 409.

    Resolves the target candidate (new vs merge with existing), creates the
    target candidate_round (`source_type='untracked_copy'`) with the source
    media refs, and triggers the Lambda feedback path so the transcript
    reprocesses against the target round's questions.
    """
    if mode not in ("new_candidate", "merge_existing"):
        raise UntrackedMutationError(
            400, f"Invalid mode {mode!r}; expected 'new_candidate' or 'merge_existing'."
        )
    if mode == "merge_existing" and not target_candidate_id:
        raise UntrackedMutationError(
            400, "target_candidate_id is required when mode='merge_existing'."
        )

    source_round = await _load_source_round(supabase, source_candidate_round_id)
    source_candidate = await _load_candidate(
        supabase, str(source_round["candidate_id"])
    )
    await _assert_source_in_org(
        supabase, str(source_candidate["requisition_id"]), org_id
    )

    target_round = await _load_target_round(
        supabase, target_requisition_id, target_round_id, org_id
    )
    resolved_target_round_id = str(target_round["id"])

    # UNTRACKED-MA: branch on the source's existing attempts (newest-first).
    imports = await _imports_for_source(supabase, source_candidate_round_id)
    exact = _exact_target_import(
        imports,
        target_requisition_id=str(target_requisition_id),
        target_round_id=resolved_target_round_id,
    )
    active = _active_import(imports)

    if exact is not None:
        if exact.get("superseded_at") is None:
            # Already the honored link for this exact (req, round). Idempotent:
            # the FE's "Process transcript" / "Send feedback request" actions
            # re-run the link before processing, so a hard 409 here made an
            # already-associated interview impossible to (re)process. Ensure the
            # round is still processable (re-copy the transcript a prior op may
            # have dropped) and update the interviewer/date if the recruiter
            # changed them, then return the existing association so the caller
            # proceeds to process / request feedback.
            return await _idempotent_existing_link(
                supabase,
                source_candidate_round_id=source_candidate_round_id,
                target_requisition_id=str(target_requisition_id),
                target_round_id=resolved_target_round_id,
                existing_import=exact,
                interviewer_email=interviewer_email,
                interviewer_name=interviewer_name,
                scheduled_at=scheduled_at,
            )
        # Reassign-back / restore: reactivate the prior superseded attempt
        # instead of inserting (which would collide on uq_import_source_target).
        return await _reactivate_existing_import(
            supabase,
            source_candidate_round_id=source_candidate_round_id,
            target_requisition_id=str(target_requisition_id),
            target_round_id=resolved_target_round_id,
            existing_import=exact,
            other_active=active,
        )

    if mode == "merge_existing":
        # Verify the candidate belongs to the target requisition.
        cand_check = await (
            supabase.table("candidates")
            .select("id, requisition_id")
            .eq("id", target_candidate_id)
            .eq("requisition_id", target_requisition_id)
            .is_("deleted_at", "null")
            .limit(1)
            .execute_async()
        )
        if not _first(cand_check.data):
            raise UntrackedMutationError(
                404,
                "Selected candidate is not in this requisition.",
            )
        resolved_candidate_id = str(target_candidate_id)
        candidate_created = False
    else:
        resolved_candidate_id, candidate_created = await _resolve_target_candidate(
            supabase,
            target_requisition_id=target_requisition_id,
            source_candidate=source_candidate,
        )
    target_candidate_id = resolved_candidate_id

    # Genuinely new target: supersede the source's current active attempt (cancel
    # its round, keep its feedback). Deferred to here — AFTER the merge_existing
    # candidate-in-requisition check above — so a failed validation (404) cannot
    # retire the prior attempt without creating a replacement. The insert below
    # restores it (_restore_prior_active) on a unique-violation conflict.
    if active is not None:
        await _supersede_prior_active(supabase, active)

    # The target candidate may already hold a (non-generic) round for this
    # round_id — the NORMAL merge case. Entering a pipeline auto-creates a
    # pending round per shared round, and the partial unique index
    # idx_candidate_rounds_unique_non_generic (candidate_id, round_id) forbids a
    # second one. So ATTACH the captured interview to that existing row (v1
    # upsert semantics) instead of inserting a duplicate — a blind insert here
    # 409'd every merge into an existing candidate. Only a genuinely new
    # candidate has no such row, in which case we insert.
    interview_fields = {
        "status": "completed",
        "source_type": "untracked_copy",
        "origin_candidate_round_id": source_candidate_round_id,
        "origin_detection_id": source_round.get("origin_detection_id"),
        # Recruiter-supplied interviewer + date override what the source carries;
        # the interviewer drives the "Send feedback request" path.
        "scheduled_at": scheduled_at or source_round.get("scheduled_at"),
        "completed_at": source_round.get("completed_at"),
        "interviewer_email": interviewer_email or source_round.get("interviewer_email"),
        "interviewer_name": interviewer_name,
        "meeting_url": source_round.get("meeting_url"),
        "recording_url": source_round.get("recording_url"),
        "transcript_url": source_round.get("transcript_url"),
    }
    existing_round = await _existing_target_round(
        supabase, target_candidate_id, resolved_target_round_id
    )
    if existing_round is not None:
        # Snapshot the pre-link round + its feedback so (a) an in-request failure
        # can roll the round back, and (b) undo can fully restore the prior
        # scorecard. Captured BEFORE the overwrite.
        prior_round = existing_round
        prior_feedback = await _load_round_feedback(supabase, str(existing_round["id"]))
        prior_round_snapshot = {
            "round": {key: existing_round.get(key) for key in _ROUND_SNAPSHOT_FIELDS},
            "feedback": prior_feedback,
        }
        await (
            supabase.table("candidate_rounds")
            .update({**interview_fields, "updated_at": _now_iso()})
            .eq("id", str(existing_round["id"]))
            .execute_async()
        )
        target_cr_row = {"id": existing_round["id"]}
        created_new_round = False
    else:
        prior_round = None
        prior_round_snapshot = None
        try:
            target_cr_insert = await (
                supabase.table("candidate_rounds")
                .insert(
                    {
                        "candidate_id": target_candidate_id,
                        "round_id": resolved_target_round_id,
                        **interview_fields,
                    }
                )
                .execute_async()
            )
        except Exception as exc:
            if is_unique_violation(exc):
                # Raced with a concurrent writer that just created the row
                # between our existence check and this insert. Restore the
                # source's prior active attempt and surface a clean 409; a retry
                # will take the update branch above.
                if active is not None:
                    await _restore_prior_active(supabase, active)
                raise UntrackedMutationError(
                    409, "That candidate already has a round for this interview."
                ) from exc
            raise
        target_cr_row = _first(target_cr_insert.data)
        if not target_cr_row:
            raise UntrackedMutationError(500, "Failed to create candidate round")
        created_new_round = True

    # UNTRACKED-MA: `uq_import_source_target` (source, target_req, target_round)
    # is the remaining DB guard — it serializes an accidental concurrent
    # same-target double-submit. Two requests can both pass the exact-target
    # pre-check above, so the loser's insert raises unique_violation (23505).
    # Insert the imports tracker BEFORE triggering feedback — that ordering
    # guarantees a losing request never fires the Lambda. On conflict we cancel
    # the candidate_round this request just created so no duplicate active round
    # survives, then surface a clean 409. (The single-active invariant across
    # DIFFERENT targets is maintained by the supersede step above, not the DB.)
    try:
        await (
            supabase.table("untracked_interview_imports")
            .insert(
                {
                    # organization_id + source_generic_candidate_id are NOT NULL
                    # (migration 66) and were populated by the v1 import path; the
                    # v2 port dropped them, so every link 500'd on a not-null
                    # violation. Both are already in scope here.
                    "organization_id": org_id,
                    "source_generic_candidate_id": str(source_candidate["id"]),
                    "source_generic_candidate_round_id": source_candidate_round_id,
                    "source_detection_id": source_round.get("origin_detection_id"),
                    "target_requisition_id": str(target_requisition_id),
                    "target_round_id": resolved_target_round_id,
                    "target_candidate_id": target_candidate_id,
                    "target_candidate_round_id": str(target_cr_row["id"]),
                    # Prior round + feedback, so undo can restore an overwritten
                    # scorecard. Null for a freshly-created round (new candidate).
                    "prior_round_snapshot": prior_round_snapshot,
                    # Must be one of the import_status_check values
                    # (copied / copied_pending_scorecard / reprocessed /
                    # reprocess_failed / failed). "imported" is NOT allowed and
                    # 400'd every link. The round is copied now; the async
                    # reprocess advances it to 'reprocessed' on its own.
                    "import_status": "copied",
                    "imported_by_user_id": imported_by_user_id,
                }
            )
            .execute_async()
        )
    except Exception as exc:
        # The tracker insert failed AFTER we wrote the candidate_round. Self-heal
        # so the merge is all-or-nothing: a round we created is cancelled; a
        # pre-existing pipeline round we updated is restored to its prior state.
        # (Without this, every tracker failure left a half-merged round — the
        # not-null, then check-constraint regressions both corrupted real rows.)
        if created_new_round:
            await _cancel_round_best_effort(supabase, str(target_cr_row["id"]))
        elif prior_round is not None:
            await _restore_round_state(supabase, prior_round)
        if is_unique_violation(exc):
            logger.warning(
                "v2 untracked-link: concurrent import lost the race "
                "source_cr_id=%s target_req_id=%s; created_new_round=%s cr_id=%s",
                source_candidate_round_id,
                str(target_requisition_id),
                created_new_round,
                str(target_cr_row["id"]),
            )
            raise UntrackedMutationError(409, "Already linked to a role") from exc
        raise

    # Copy the interview transcript onto the target round. The feedback Lambda
    # reads transcripts by candidate_round_id; the untracked interview's transcript
    # lives on the SOURCE round (in the transcripts table), so without this copy the
    # target round has no media and feedback processing produces nothing — this is
    # the gap that made every merged interview fail to generate feedback. Best
    # effort: a copy failure leaves the association intact (recruiter can reprocess).
    try:
        await _copy_interview_transcript(
            supabase, source_candidate_round_id, str(target_cr_row["id"])
        )
    except Exception as exc:
        logger.error(
            "v2 untracked-link: interview transcript copy failed cr_id=%s err=%s",
            str(target_cr_row["id"]),
            str(exc),
        )

    # No auto-processing: the recruiter explicitly chooses what to do next with
    # the returned target_candidate_round_id — "Send feedback request" (the
    # interviewer's assessment → a real scorecard, the primary path) or "Process
    # transcript" (a quick rating from the interview alone). Auto-triggering the
    # Lambda here produced only a thin rating and tripped the trigger CAS guard.
    return {
        "untracked_id": source_candidate_round_id,
        "target_requisition_id": str(target_requisition_id),
        "target_round_id": resolved_target_round_id,
        "target_candidate_id": target_candidate_id,
        "target_candidate_round_id": str(target_cr_row["id"]),
        "candidate_created": candidate_created,
    }


async def _idempotent_existing_link(
    supabase,
    *,
    source_candidate_round_id: str,
    target_requisition_id: str,
    target_round_id: str,
    existing_import: dict,
    interviewer_email: Optional[str],
    interviewer_name: Optional[str],
    scheduled_at: Optional[str],
) -> dict:
    """Re-link to the SAME already-active target: a no-op association that keeps
    the round processable.

    The combined FE actions (Process transcript / Send feedback request) re-run
    the link before processing, so when the interview is already honored on this
    exact (req, round) we must NOT 409 — that made re-processing an associated
    interview impossible. Update the interviewer/date if the recruiter changed
    them and re-copy the interview transcript (idempotent upsert; defends against
    a transcript a prior step dropped), then return the existing association.
    """
    existing_cr_id = existing_import.get("target_candidate_round_id")
    if existing_cr_id:
        fields: dict = {}
        if interviewer_email:
            fields["interviewer_email"] = interviewer_email
        if interviewer_name:
            fields["interviewer_name"] = interviewer_name
        if scheduled_at:
            fields["scheduled_at"] = scheduled_at
        if fields:
            fields["updated_at"] = _now_iso()
            try:
                await (
                    supabase.table("candidate_rounds")
                    .update(fields)
                    .eq("id", str(existing_cr_id))
                    .execute_async()
                )
            except Exception as exc:
                logger.error(
                    "v2 untracked-link: interviewer/date update failed (idempotent) "
                    "cr_id=%s err=%s",
                    str(existing_cr_id),
                    str(exc),
                )
        try:
            await _copy_interview_transcript(
                supabase, source_candidate_round_id, str(existing_cr_id)
            )
        except Exception as exc:
            logger.error(
                "v2 untracked-link: transcript re-copy failed (idempotent) "
                "cr_id=%s err=%s",
                str(existing_cr_id),
                str(exc),
            )
    return {
        "untracked_id": source_candidate_round_id,
        "target_requisition_id": str(target_requisition_id),
        "target_round_id": str(target_round_id),
        "target_candidate_id": existing_import.get("target_candidate_id"),
        "target_candidate_round_id": str(existing_cr_id) if existing_cr_id else None,
        "candidate_created": False,
    }


async def _reactivate_existing_import(
    supabase,
    *,
    source_candidate_round_id: str,
    target_requisition_id: str,
    target_round_id: str,
    existing_import: dict,
    other_active: Optional[dict],
) -> dict:
    """Reassign-back: restore a previously superseded attempt as the honored one.

    UNTRACKED-MA: the source was once linked to this exact (req, round) and later
    reassigned away. Instead of inserting (which would collide on
    uq_import_source_target) we clear `superseded_at` on the existing row and
    restore its candidate_round to 'completed'. Any OTHER currently-active
    attempt is superseded (its round cancelled, feedback kept).

    The interview transcript is RE-COPIED onto the restored round: if the attempt
    was previously undone, undo_untracked_link deleted the target round's copied
    transcript, so reactivating without re-copying would leave a media-less round
    that fails the moment the recruiter processes it. Copy is idempotent (upsert).

    Like the main link path, reactivate does NOT auto-process — the recruiter
    chooses "Process transcript" or "Send feedback request" next (spec locked
    decision 1). Auto-triggering here re-ran the Lambda against the round before
    the recruiter chose and produced a thin/stale rating.
    """
    restored_cr_id = existing_import.get("target_candidate_round_id")

    # Supersede any other active attempt first so single-active holds even if a
    # later step fails partway.
    if other_active is not None and str(other_active.get("id") or "") != str(
        existing_import.get("id") or ""
    ):
        await _supersede_prior_active(supabase, other_active)

    await (
        supabase.table("untracked_interview_imports")
        .update({"superseded_at": None, "updated_at": _now_iso()})
        .eq("id", str(existing_import["id"]))
        .execute_async()
    )

    # Restore the prior round to the active pipeline (it was cancelled when this
    # attempt was superseded away). Best-effort, same swallow contract as cancel.
    if restored_cr_id:
        try:
            await (
                supabase.table("candidate_rounds")
                .update({"status": "completed", "updated_at": _now_iso()})
                .eq("id", str(restored_cr_id))
                .execute_async()
            )
        except Exception as exc:
            logger.error(
                "v2 untracked-link: failed to restore reactivated round cr_id=%s err=%s",
                str(restored_cr_id),
                str(exc),
            )

        # Re-copy the interview transcript a prior undo may have deleted, so the
        # restored round is processable. Best-effort: a copy failure leaves the
        # association intact (recruiter can retry).
        try:
            await _copy_interview_transcript(
                supabase, source_candidate_round_id, str(restored_cr_id)
            )
        except Exception as exc:
            logger.error(
                "v2 untracked-link: interview transcript re-copy failed (reactivate) "
                "cr_id=%s err=%s",
                str(restored_cr_id),
                str(exc),
            )

    return {
        "untracked_id": source_candidate_round_id,
        "target_requisition_id": str(target_requisition_id),
        "target_round_id": str(target_round_id),
        "target_candidate_id": existing_import.get("target_candidate_id"),
        "target_candidate_round_id": str(restored_cr_id) if restored_cr_id else None,
        "candidate_created": False,
    }


async def get_untracked_packet(
    supabase,
    *,
    org_id: str,
    source_candidate_round_id: str,
) -> dict:
    """Return a CandidatePacket-shaped response for an untracked interview.

    The standard `get_candidate_packet` RPC doesn't traverse rows under
    system-template (materialized) requisitions, so the v2 PacketDrawer
    came up blank when pointed at the captured candidate. Mirrors the v1
    `/api/v1/requisitions/untracked/interviews/{id}/packet` shape but
    reformats the payload to match the v2 FE's `CandidatePacket` so the
    drawer renders without any untracked-specific branching downstream.

    Returns null candidate / empty rounds if the source is missing or
    crosses org — never raises 404 for a typed-but-unknown id, the FE
    treats `{candidate: null}` as "drawer should empty out gracefully."
    """
    source_round = await _load_source_round(supabase, source_candidate_round_id)
    source_candidate = await _load_candidate(
        supabase, str(source_round["candidate_id"])
    )
    await _assert_source_in_org(
        supabase, str(source_candidate["requisition_id"]), org_id
    )

    # Round header (name + duration_minutes etc.) for the FE round rail.
    round_id = str(source_round.get("round_id") or "")
    round_result = await (
        supabase.table("rounds")
        .select(
            "id, requisition_id, round_number, name, category, "
            "duration_minutes, description, skills, guidelines, "
            "created_at, updated_at"
        )
        .eq("id", round_id)
        .is_("deleted_at", "null")
        .limit(1)
        .execute_async()
    )
    round_def = _first(round_result.data)
    if not round_def:
        raise UntrackedMutationError(404, "Round definition not found")

    # Round questions in the FE shape.
    questions_result = await (
        supabase.table("feedback_questions")
        .select("id, round_id, question_number, heading, description")
        .eq("round_id", round_id)
        .is_("deleted_at", "null")
        .order("question_number", desc=False)
        .execute_async()
    )
    questions = questions_result.data or []

    # Feedback entries keyed by feedback_question_id.
    feedback_result = await (
        supabase.table("candidate_feedback")
        .select(
            "id, candidate_round_id, feedback_question_id, feedback_text, "
            "evidence, evidence_status, source, created_at"
        )
        .eq("candidate_round_id", source_candidate_round_id)
        .order("created_at", desc=False)
        .execute_async()
    )
    feedback_rows = feedback_result.data or []
    feedback_by_question: dict[str, list[dict]] = {}
    for fb in feedback_rows:
        qid = str(fb.get("feedback_question_id") or "")
        if not qid:
            continue
        feedback_by_question.setdefault(qid, []).append(fb)

    # Recording metadata (mirrors what /roles/.../packet returns: status,
    # duration, has_transcript). Full URL + segments are fetched lazily by
    # the FE's Round Replay tab via /candidate-rounds/{id}/recording-url +
    # /transcript — those endpoints already work for any CR id.
    recall_result = await (
        supabase.table("recall_bots")
        .select(
            "id, status, recording_duration_seconds, transcript_ready, "
            "joined_at"
        )
        .eq("candidate_round_id", source_candidate_round_id)
        .order("joined_at", desc=True)
        .limit(1)
        .execute_async()
    )
    recall = _first(recall_result.data)

    question_summaries = source_round.get("question_summaries") or {}

    # Match v2 FE's CandidatePacketFeedbackQuestion shape.
    fb_questions_out: list[dict] = []
    for q in questions:
        q_id = str(q.get("id") or "")
        q_num = q.get("question_number") or 0
        summary = None
        if isinstance(question_summaries, dict):
            summary = (
                question_summaries.get(str(q_num))
                or question_summaries.get(q_id)
            )
        fb_questions_out.append(
            {
                "id": q.get("id"),
                "question_number": q_num,
                "heading": q.get("heading") or "",
                "description": q.get("description"),
                "summary": summary,
                "feedback_entries": feedback_by_question.get(q_id, []),
            }
        )

    # Round header with embedded feedback_questions (v2 FE's CandidatePacketEntry.round shape).
    round_out = {
        "id": round_def.get("id"),
        "requisition_id": round_def.get("requisition_id"),
        "round_number": round_def.get("round_number") or 1,
        "name": round_def.get("name") or "Untracked interview",
        "category": round_def.get("category") or "panel",
        "duration_minutes": round_def.get("duration_minutes") or 45,
        "description": round_def.get("description"),
        "skills": round_def.get("skills") or [],
        "guidelines": round_def.get("guidelines") or [],
        "feedback_questions": [
            {
                "id": q.get("id"),
                "round_id": round_id,
                "question_number": q.get("question_number") or 0,
                "heading": q.get("heading") or "",
                "description": q.get("description") or "",
            }
            for q in questions
        ],
        "created_at": round_def.get("created_at"),
        "updated_at": round_def.get("updated_at"),
    }

    candidate_round_out = {
        "id": source_round.get("id"),
        "candidate_id": source_round.get("candidate_id"),
        "round_id": source_round.get("round_id"),
        "status": source_round.get("status") or "completed",
        "scorecard_status": "complete"
        if (source_round.get("summary") or feedback_rows)
        else "pending",
        "rating": source_round.get("rating"),
        "summary": source_round.get("summary") or "",
        "question_summaries": question_summaries
        if isinstance(question_summaries, dict)
        else {},
        "feedback_approved_at": None,
        "feedback_approved_by_email": None,
        "scheduled_at": source_round.get("scheduled_at"),
        "scheduling_timezone": None,
        "completed_at": source_round.get("completed_at"),
        "interviewer_email": source_round.get("interviewer_email"),
        "interviewer_name": None,
        "meeting_url": source_round.get("meeting_url"),
        "scorecard": [],
    }

    recording_out = None
    if recall:
        recording_out = {
            "status": recall.get("status") or "pending",
            "duration_seconds": recall.get("recording_duration_seconds"),
            "has_transcript": bool(recall.get("transcript_ready")),
        }
    elif source_round.get("recording_url") or source_round.get("transcript_url"):
        recording_out = {
            "status": "done",
            "duration_seconds": None,
            "has_transcript": bool(source_round.get("transcript_url")),
        }

    candidate_out = {
        "id": source_candidate.get("id"),
        "requisition_id": source_candidate.get("requisition_id"),
        "name": source_candidate.get("name") or "Untracked candidate",
        "email": source_candidate.get("email") or "",
        "phone": source_candidate.get("phone"),
        "resume_url": source_candidate.get("resume_url"),
        "avatar_initials": _initials(source_candidate.get("name") or ""),
        "avatar_color": "#EADFD4",
        "status": "active",
        "final_verdict": None,
        "current_round_id": source_round.get("round_id"),
        "tags": [],
        "source": "untracked_capture",
        "created_at": source_round.get("scheduled_at"),
        "updated_at": source_round.get("scheduled_at"),
    }

    return {
        "candidate": candidate_out,
        "rounds": [
            {
                "round": round_out,
                "candidate_round": candidate_round_out,
                "feedback_questions": fb_questions_out,
                "assessment": None,
                "recording": recording_out,
            }
        ],
    }


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    return "".join(p[0].upper() for p in parts[:2]) or "?"


async def mark_not_interview(
    supabase,
    *,
    org_id: str,
    source_candidate_round_id: str,
    actor_user_id: Optional[str],
) -> dict:
    """Mark an untracked row as 'not an interview' (terminal). Writes a
    dismissed import row so the listing filter (status='dismissed') hides
    it on the next call. Idempotent — re-dismissing is a no-op.
    """
    source_round = await _load_source_round(supabase, source_candidate_round_id)
    source_candidate = await _load_candidate(
        supabase, str(source_round["candidate_id"])
    )
    await _assert_source_in_org(
        supabase, str(source_candidate["requisition_id"]), org_id
    )

    imports = await _imports_for_source(supabase, source_candidate_round_id)
    latest = imports[0] if imports else None
    if latest and str(latest.get("import_status") or "") == "dismissed":
        return {
            "untracked_id": source_candidate_round_id,
            "status": "dismissed",
        }
    # An active (honored) link blocks dismissal. Superseded prior attempts do
    # not — they are kept history, not the live association.
    if _active_import(imports) is not None:
        raise UntrackedMutationError(
            409, "Already linked to a role; cannot mark as not-an-interview"
        )

    # The pre-check above is a fast path only. Under a double-submit (or a
    # dismiss racing a concurrent link), a non-dismissed import row can land
    # between the read and this insert; the partial unique index then rejects
    # the conflicting write with Postgres unique_violation (23505). Map that
    # to a clean 409 rather than letting the raw DB error escape — no
    # second-side-effect occurs because this branch only writes the one row.
    try:
        await (
            supabase.table("untracked_interview_imports")
            .insert(
                {
                    "source_generic_candidate_round_id": source_candidate_round_id,
                    "source_detection_id": source_round.get("origin_detection_id"),
                    "import_status": "dismissed",
                    "imported_by_user_id": actor_user_id,
                }
            )
            .execute_async()
        )
    except Exception as exc:
        if is_unique_violation(exc):
            logger.warning(
                "v2 untracked-mark-not-interview: concurrent write lost the race "
                "source_cr_id=%s",
                source_candidate_round_id,
            )
            raise UntrackedMutationError(
                409, "This interview was just acted on; refresh and try again."
            ) from exc
        raise
    return {
        "untracked_id": source_candidate_round_id,
        "status": "dismissed",
    }


async def undo_link(
    supabase,
    *,
    org_id: str,
    source_candidate_round_id: str,
) -> dict:
    """Undo the active association of an untracked interview.

    Restores the prior round + scorecard from the snapshot (or cancels a
    freshly-created round), drops the copied transcript + feedback token, and
    supersedes the import so the interview returns to 'available'. Atomic via the
    undo_untracked_link SECURITY DEFINER RPC.
    """
    try:
        result = await supabase.rpc(
            "undo_untracked_link",
            {
                "p_org_id": org_id,
                "p_source_cr_id": source_candidate_round_id,
            },
        )
    except Exception as exc:
        # P0002 raise from the RPC when there's no honored attempt for this org.
        if "no active untracked link" in str(exc).lower():
            raise UntrackedMutationError(404, "No active association to undo") from exc
        raise
    data = result.data if result is not None else None
    return data or {
        "untracked_id": source_candidate_round_id,
        "restored_prior_scorecard": False,
    }


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"
