"""Manipulation of intake_sessions.active_modality — the concurrency lock that
prevents voice + text sessions from running in parallel.

State transitions (per spec §8.3):
  null  -> 'voice'  (voice start)
  null  -> 'text'   (text first message)
  'voice' -> null   (voice ended or drained)
  'text'  -> null   (text idle timeout or user navigated away)

BE-A2: acquisition is now DETERMINISTIC. The conditional UPDATE lives in the
`set_active_modality` SECURITY DEFINER RPC (migration 103) — Postgres serializes
the row lock so exactly one concurrent writer wins; the losers get a definite
"false" instead of a racy read-modify-write. The old SELECT-then-UPDATE
`acquire_modality` is gone.

Two acquire shapes remain:
  - `require_no_other_modality`: deterministic acquire used as the pre-flight gate
    by voice/start, text/messages and switch->voice. Wins for a free lock or the
    same modality (idempotent reconnect); raises ModalityConflictError when the
    OTHER modality holds it (-> HTTP 409), LookupError when the session row does
    not belong to the caller (-> HTTP 404).
  - `set_modality`: UNCONDITIONAL setter used after the caller has already proven
    exclusivity — switch->text (the voice holder has drained) and switch->none /
    release (modality=None clears the lock). It is deliberately NOT routed through
    the acquire RPC: a forced handoff must overwrite a still-set 'voice' lock.
"""

from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)

Modality = Literal["voice", "text"]


class ModalityConflictError(RuntimeError):
    """Raised when a session has the other modality already locked."""

    def __init__(self, session_id: UUID, held: str, requested: str):
        self.session_id = session_id
        self.held = held
        self.requested = requested
        super().__init__(
            f"session {session_id} cannot acquire {requested!r} — the other modality holds the lock"
        )


async def _session_exists(
    supabase,
    session_id: UUID,
    organization_id: Optional[UUID],
    user_id: Optional[UUID],
) -> bool:
    """Scoped existence check so a genuinely-missing session 404s instead of 409s.

    The acquire RPC's WHERE clause folds "row missing", "wrong tenant" and "other
    modality holds" all into a single false; this read separates the first two
    (LookupError -> 404) from the real conflict (ModalityConflictError -> 409)."""
    query = (
        supabase.table("intake_sessions")
        .select("id")
        .eq("id", str(session_id))
    )
    if organization_id is not None:
        query = query.eq("organization_id", str(organization_id))
    if user_id is not None:
        query = query.eq("user_id", str(user_id))
    result = await query.execute_async()
    data = result.data
    return bool(data)


async def require_no_other_modality(
    supabase,
    session_id: UUID,
    self_modality: Modality,
    organization_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
) -> None:
    """Deterministically acquire `self_modality` via the set_active_modality RPC.

    Raises ModalityConflictError (-> 409) if the OTHER modality already holds the
    lock, LookupError (-> 404) if the session row does not belong to the caller.
    Wins silently for a free lock or the same modality (idempotent reconnect).
    """
    won = await supabase.rpc(
        "set_active_modality",
        {
            "p_session_id": str(session_id),
            "p_modality": self_modality,
            "p_user_id": str(user_id) if user_id is not None else None,
        },
    )
    if _rpc_won(won):
        logger.info("modality_acquired", session_id=str(session_id), modality=self_modality)
        return
    # Lost the conditional UPDATE: disambiguate missing/cross-tenant (404) from a
    # genuine other-modality conflict (409).
    if not await _session_exists(supabase, session_id, organization_id, user_id):
        raise LookupError(f"intake_sessions row {session_id} not found")
    raise ModalityConflictError(session_id=session_id, held="other", requested=self_modality)


async def set_modality(
    supabase,
    session_id: UUID,
    modality: Optional[Modality],
    organization_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
) -> None:
    """Unconditional setter — used by switch endpoints after a successful drain
    (force handoff) and to clear the lock (`modality=None` serializes to SQL NULL).
    organization_id / user_id, when provided, scope the query to prevent cross-tenant access.
    """
    query = supabase.table("intake_sessions").update({
        "active_modality": modality,
    }).eq("id", str(session_id))
    if organization_id is not None:
        query = query.eq("organization_id", str(organization_id))
    if user_id is not None:
        query = query.eq("user_id", str(user_id))
    await query.execute_async()
    logger.info("modality_set", session_id=str(session_id), modality=modality)


def _rpc_won(resp) -> bool:
    """Unwrap the boolean returned by the set_active_modality RPC.

    The SupabaseAdminClient.rpc() returns a TableResponse whose `.data` is the
    scalar function result; tests may pass the bare bool. Treat only an explicit
    True as a win."""
    data = getattr(resp, "data", resp)
    return data is True
