"""Coverage tracker — post-turn LLM backstop (spec section 7).

Runs as an asyncio.create_task after each user turn. Reads current_answers,
last user turn, and recent context. Calls Sonnet 4.6, parses the patch,
writes via update_current_answers RPC.

Design choices:
- Fire-and-forget: never raises to the caller. Failures are logged + returned in result.
- Debounced via the caller (~200ms) so agent tool calls land first.
- Only emits keys the user actually addressed — narrow patches keep agent writes safe.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import structlog

from intake_core.persistence import (
    aload_session,
    aupdate_current_answers,
    load_session,
    update_current_answers,
)
from intake_core.prompts.tracker import (
    TRACKER_SYSTEM_PROMPT,
    build_tracker_prompt,
    parse_tracker_response,
)

logger = structlog.get_logger(__name__)


def _is_async_client(client) -> bool:
    """Return True for SupabaseAdminClient (async rpc), False for supabase-py sync client."""
    rpc = getattr(client, "rpc", None)
    return rpc is not None and inspect.iscoroutinefunction(rpc)


async def run_coverage_tracker(
    supabase_client,
    anthropic_client,
    model: str,
    session_id: str,
    last_user_turn: str,
    debounce_ms: int = 200,
) -> dict[str, Any]:
    """Run a single coverage tracker pass. Returns {ok, applied, patch?, error?}.

    Supports both async (SupabaseAdminClient — FastAPI/text path) and sync
    (supabase-py create_client — voice agent path) Supabase clients.
    """
    if debounce_ms > 0:
        await asyncio.sleep(debounce_ms / 1000.0)

    async_client = _is_async_client(supabase_client)

    try:
        if async_client:
            session = await aload_session(supabase_client, session_id)
        else:
            session = await asyncio.get_event_loop().run_in_executor(
                None, load_session, supabase_client, session_id
            )
    except Exception as e:
        logger.warning("tracker_load_failed", session_id=session_id, error=str(e))
        return {"ok": False, "error": f"load: {e}", "applied": False}

    current = session.get("current_answers") or {}
    turns = session.get("turns") or []

    user_prompt = build_tracker_prompt(
        current_answers=current,
        last_user_turn=last_user_turn,
        recent_turns=turns,
    )

    try:
        response = await anthropic_client.messages.create(
            model=model,
            max_tokens=1024,
            temperature=0,
            system=TRACKER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text
    except Exception as e:
        logger.warning("tracker_llm_failed", session_id=session_id, error=str(e))
        return {"ok": False, "error": str(e)[:200], "applied": False}

    patch = parse_tracker_response(raw)
    if not patch:
        return {"ok": True, "applied": False, "patch": {}}

    try:
        if async_client:
            await aupdate_current_answers(supabase_client, session_id, patch)
        else:
            await asyncio.get_event_loop().run_in_executor(
                None, update_current_answers, supabase_client, session_id, patch
            )
    except Exception as e:
        logger.warning("tracker_apply_failed", session_id=session_id, error=str(e))
        return {"ok": False, "error": f"apply: {e}", "applied": False, "patch": patch}

    logger.info("tracker_applied", session_id=session_id, qids=list(patch.keys()))
    return {"ok": True, "applied": True, "patch": patch}
