"""Persistence helpers for intake_sessions. Uses Supabase RPC functions for safe
JSONB mutations (avoid read-modify-write races on turns[] and current_answers).

The RPC functions (intake_sessions_append_turn, intake_sessions_merge_answers,
intake_sessions_set_stage) are created in migration 95.

Two sets of helpers are provided:
- Sync (load_session, append_turn, update_current_answers, update_process_stage):
  for the Lambda path which uses supabase-py directly (rpc() returns a builder,
  .execute() runs it synchronously).
- Async (aload_session, aappend_turn, aupdate_current_answers,
  aupdate_process_stage): for the FastAPI text path which uses the repo's
  SupabaseAdminClient where rpc() is async and returns a TableResponse directly,
  and table operations use execute_async().
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Sync helpers — Lambda path (supabase-py client)
# ---------------------------------------------------------------------------

def load_session(client, session_id: str) -> dict:
    """Load a full intake_sessions row by ID."""
    result = client.table("intake_sessions").select("*").eq("id", session_id).single().execute()
    return result.data


def append_turn(client, session_id: str, turn: dict) -> None:
    """Append a turn to intake_sessions.turns via RPC (atomic JSONB append)."""
    client.rpc(
        "intake_sessions_append_turn",
        {"p_session_id": session_id, "p_turn": turn},
    ).execute()


def update_current_answers(client, session_id: str, patch: dict) -> None:
    """Merge a JSON patch into current_answers via RPC (atomic JSONB merge)."""
    client.rpc(
        "intake_sessions_merge_answers",
        {"p_session_id": session_id, "p_patch": patch},
    ).execute()


def update_process_stage(
    client,
    session_id: str,
    stage_name: str,
    status: str,
    output: Optional[dict] = None,
    error: Optional[str] = None,
) -> None:
    """Append or update a stage in process_stages via RPC."""
    client.rpc(
        "intake_sessions_set_stage",
        {
            "p_session_id": session_id,
            "p_stage_name": stage_name,
            "p_status": status,
            "p_output": output,
            "p_error": error,
        },
    ).execute()


# ---------------------------------------------------------------------------
# Async helpers — FastAPI text path (SupabaseAdminClient)
# SupabaseAdminClient.rpc() is async and returns a TableResponse directly;
# table operations expose execute_async() for non-blocking I/O.
# ---------------------------------------------------------------------------

async def aload_session(client, session_id: str) -> dict:
    """Load a full intake_sessions row by ID (async)."""
    result = await client.table("intake_sessions").select("*").eq("id", session_id).single().execute_async()
    return result.data


async def aappend_turn(client, session_id: str, turn: dict) -> None:
    """Append a turn to intake_sessions.turns via RPC (atomic JSONB append, async)."""
    await client.rpc(
        "intake_sessions_append_turn",
        {"p_session_id": session_id, "p_turn": turn},
    )


async def aupdate_current_answers(client, session_id: str, patch: dict) -> None:
    """Merge a JSON patch into current_answers via RPC (atomic JSONB merge, async)."""
    await client.rpc(
        "intake_sessions_merge_answers",
        {"p_session_id": session_id, "p_patch": patch},
    )


async def aupdate_process_stage(
    client,
    session_id: str,
    stage_name: str,
    status: str,
    output: Optional[dict] = None,
    error: Optional[str] = None,
) -> None:
    """Append or update a stage in process_stages via RPC (async)."""
    await client.rpc(
        "intake_sessions_set_stage",
        {
            "p_session_id": session_id,
            "p_stage_name": stage_name,
            "p_status": status,
            "p_output": output,
            "p_error": error,
        },
    )
