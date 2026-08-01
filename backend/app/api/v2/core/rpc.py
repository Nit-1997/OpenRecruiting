"""
RPC plumbing for v2 services.

`call_rpc` wraps `supabase.rpc(...)` and converts Postgres errors
(`RpcError`) into v2 domain exceptions via `map_rpc_error`. The mapping is
exhaustive over the codes actually raised by migrations 81–84 (see
`deploy-config/sql/81..84-*.sql`).

NB: `RpcError.code` carries the Postgres SQLSTATE (P0001, P0002, ...).
The user-visible message lives in `RpcError.message` and — for raised P0001
exceptions — is itself the stable machine-readable code (LAST_ROUND, etc.).
"""

from app.services.supabase import RpcError

from app.api.v2.core.exceptions import (
    ConflictError,
    NotFoundError,
    UpstreamServiceError,
    V2DomainError,
    ValidationError,
)


def map_rpc_error(err: RpcError) -> V2DomainError:
    """Map a Postgres RPC error to a v2 domain exception.

    The match key is (SQLSTATE, message). All known P0001 messages from
    migrations 81–84 have an explicit arm. Unknown P0001 codes pass through
    as ConflictError so the caller still sees the machine-readable code.
    Anything else surfaces as UpstreamServiceError (502) — that means the
    RPC failed for a reason we don't model.
    """
    sqlstate = err.code
    msg = (err.message or "").strip()

    match (sqlstate, msg):
        case ("P0002", _):
            return NotFoundError("Resource not found")

        # ---- migration 82 (shared-plan mutations) ----
        case ("P0001", "LAST_ROUND"):
            return ConflictError(
                "LAST_ROUND",
                "Cannot delete the last shared round in the plan",
            )
        case ("P0001", "ALREADY_REMOVED"):
            return ConflictError(
                "ALREADY_REMOVED",
                "This round has already been removed from the plan",
            )
        case ("P0001", "WRONG_PATH"):
            return ValidationError(
                "Custom rounds use the candidate-journey delete endpoint"
            )
        case ("P0001", "INVALID_ROUND"):
            return ValidationError(
                "Invalid round configuration in reorder payload"
            )
        case ("P0001", "INVALID_ORDER"):
            return ValidationError(
                "Invalid order in reorder payload"
            )
        case ("P0001", "INCOMPLETE_REORDER"):
            return ValidationError(
                "Reorder payload is incomplete — must include all active rounds"
            )
        case ("P0001", "INVALID_PERMUTATION"):
            return ValidationError(
                "Reorder payload is not a valid 1..N permutation"
            )

        # ---- migration 83 (candidate / journey mutations) ----
        case ("P0001", "REQ_CLOSED"):
            return ConflictError(
                "REQ_CLOSED",
                "Requisition is closed; reopen before this action",
            )
        # ---- migration 127 (candidates attach to published roles only) ----
        case ("P0001", "REQ_NOT_PLANNED"):
            return ConflictError(
                "REQ_NOT_PLANNED",
                "Complete this role's intake and publish it before adding candidates",
            )
        case ("P0001", "CANDIDATE_INACTIVE"):
            return ConflictError(
                "CANDIDATE_INACTIVE",
                "Cannot modify a candidate that is hired/rejected/withdrawn",
            )
        case ("P0001", "NOT_PENDING"):
            return ConflictError(
                "NOT_PENDING",
                "This round is already scheduled/completed and can't be removed",
            )

        # ---- migration 84 (journey mutations) ----
        case ("P0001", "SCHEDULED_IN_PAST"):
            # Pydantic schema in v2 also enforces this (migration 87 +
            # schemas/interview.py); the RPC guard is defence-in-depth.
            # Surface as 422 validation so the FE treats it the same as
            # the FE-side past-time check.
            return ValidationError(
                "scheduled_at must not be in the past"
            )
        case ("P0001", "NOT_SCHEDULABLE"):
            return ConflictError(
                "NOT_SCHEDULABLE",
                (
                    "Candidate round is not in a schedulable state "
                    "(must be pending or cancelled — completed and in-progress "
                    "rounds cannot be (re)scheduled here)"
                ),
            )
        case ("P0001", "NOT_RESCHEDULABLE"):
            return ConflictError(
                "NOT_RESCHEDULABLE",
                "Only scheduled rounds can be rescheduled — use POST to schedule from another state",
            )
        case ("P0001", "ALREADY_COMPLETED"):
            return ConflictError(
                "ALREADY_COMPLETED",
                "Cannot cancel a completed round",
            )
        case ("P0001", "NOT_OPEN"):
            return ConflictError(
                "NOT_OPEN",
                (
                    "Feedback can only be submitted for scheduled or in-progress rounds. "
                    "Use /reprocess for completed rounds."
                ),
            )
        case ("P0001", "BAD_QUESTION"):
            return ValidationError(
                "One or more feedback_question_id values do not belong to this round"
            )

        # ---- migration 106 (admin atomic submit_feedback) ----
        # An incoming item carried an id that is not a feedback row on this
        # candidate round. The old per-row loop returned 404 for this case; the
        # RPC raises it AFTER rolling back the whole transaction so nothing is
        # partially written.
        case ("P0001", "FEEDBACK_NOT_FOUND"):
            return NotFoundError(
                "Feedback entry not found for this candidate round"
            )

        # ---- migration 105 (admin atomic mutations) ----
        # The happy-path "already/​not archived" cases are caught by the router's
        # pre-read (400); these RPC-raised arms are defence-in-depth for a state
        # change between the pre-read and the RPC, surfaced as a 409 conflict.
        case ("P0001", "ALREADY_ARCHIVED"):
            return ConflictError(
                "ALREADY_ARCHIVED",
                "Organization is already archived",
            )
        case ("P0001", "NOT_ARCHIVED"):
            return ConflictError(
                "NOT_ARCHIVED",
                "Organization is not archived",
            )

        case ("P0001", code) if code:
            # Unknown P0001 code from an RPC we did not catalogue —
            # treat as a state conflict and surface the code verbatim.
            return ConflictError(code, code)

        # SQLSTATE 23505 = unique_violation. Common causes:
        #  - candidates(requisition_id, email) — duplicate email per role
        #  - candidate_rounds(candidate_id, round_id) — guarded by ON CONFLICT
        #    in the RPC; only fires if a future caller bypasses that guard
        # Surface as a clean 409 so the FE shows actionable copy instead of
        # the catch-all "Service unavailable" 5xx.
        case ("23505", msg) if msg and "idx_unique_candidate_email" in msg:
            return ConflictError(
                "DUPLICATE_EMAIL",
                "A candidate with this email already exists in this role.",
            )
        case ("23505", _):
            return ConflictError(
                "DUPLICATE",
                "This record already exists.",
            )

        case _:
            return UpstreamServiceError(
                f"RPC error: {sqlstate or '?'} {msg or 'unknown'}"
            )


async def call_rpc(supabase, name: str, params: dict):
    """Execute a Supabase RPC and convert RpcError to a v2 domain exception.

    Returns the unwrapped `result.data` (the RPC's JSON return value).
    """
    try:
        result = await supabase.rpc(name, params)
    except RpcError as err:
        raise map_rpc_error(err)
    return result.data
