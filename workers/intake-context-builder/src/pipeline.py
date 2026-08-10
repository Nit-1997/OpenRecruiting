"""Pipeline orchestration: 4 stages with progressive Supabase writes for live UI."""

from __future__ import annotations

from typing import Any

import structlog

from intake_core.persistence import load_session, update_process_stage  # noqa

from .settings import load_settings
from .clients.llm import get_llm_client, close_llm_client
from .clients.supabase import get_supabase_client, close_supabase_client
from .clients.cortex_mcp import get_mcp_client, close_mcp_client
from .clients.cortex_token import fetch_service_token
from .stages.check_context import check_context
from .stages.parse_jd import parse_jd
from .stages.query_cortex import query_cortex
from .stages.synthesize import synthesize_answers

logger = structlog.get_logger(__name__)


async def run_pipeline(session_id: str, include_turns: bool) -> dict[str, Any]:
    """Run all 4 stages, writing progress to intake_sessions.process_stages.

    Per CLAUDE.md mandatory Lambda rules: all async clients are closed in finally,
    module globals are reset. Two invocations on the same warm container must not
    crash from a closed event loop.
    """
    settings = load_settings()

    sb = get_supabase_client(settings.supabase_url, settings.supabase_secret_key)
    llm = get_llm_client()

    try:
        # Mark overall status: prefilling
        sb.table("intake_sessions").update({"status": "prefilling", "process_status": "running"}).eq("id", session_id).execute()

        session = load_session(sb, session_id)
        form_data = session["form_data"]
        role_title = form_data.get("role_name", "")
        jd_text = form_data.get("jd_text")

        # Cortex is scoped to the session's org: mint a per-org token from the
        # backend (which holds the signing key) and bind the MCP client to it.
        cortex_jwt = await fetch_service_token(
            settings.cortex_token_url, settings.internal_api_secret, session["organization_id"]
        )
        mcp = get_mcp_client(settings.cortex_mcp_url, cortex_jwt)

        # Stage 1: check_context
        update_process_stage(sb, session_id, stage_name="check_context", status="running")
        ctx_out = await check_context(mcp_client=mcp, role_title=role_title)
        update_process_stage(sb, session_id, stage_name="check_context", status="completed", output=ctx_out)

        # Stage 2: parse_jd
        update_process_stage(sb, session_id, stage_name="parse_jd", status="running")
        jd_out = await parse_jd(llm=llm, model=settings.parse_jd_model, jd_text=jd_text)
        update_process_stage(sb, session_id, stage_name="parse_jd", status="completed", output=jd_out)

        # Stage 3: query_cortex
        update_process_stage(sb, session_id, stage_name="query_cortex", status="running")
        cortex_out = await query_cortex(mcp_client=mcp, mode=ctx_out["mode"], role_title=role_title)
        update_process_stage(sb, session_id, stage_name="query_cortex", status="completed", output={"counts": {k: len(v) for k, v in cortex_out.items()}})

        # Stage 4: synthesize
        update_process_stage(sb, session_id, stage_name="synthesize", status="running")
        answers = await synthesize_answers(
            llm=llm,
            model=settings.synthesize_model,
            form_data=form_data,
            jd_facts=jd_out.get("facts", {}),
            cortex_data=cortex_out,
        )
        # Write prefilled_answers; also initialize current_answers if not yet set
        # process_error must be cleared here: it is only ever written on failure,
        # so without this a session that failed once keeps the stale message
        # after a successful re-run and the UI goes on reporting "We couldn't
        # prefill from your context" over perfectly good answers.
        if not include_turns:
            sb.table("intake_sessions").update({
                "prefilled_answers": answers,
                "current_answers": answers,
                "status": "ready",
                "process_status": "idle",
                "process_error": None,
            }).eq("id", session_id).execute()
        else:
            # Re-prefill: only update prefilled_answers, leave current_answers alone
            sb.table("intake_sessions").update({
                "prefilled_answers": answers,
                "process_status": "idle",
                "process_error": None,
            }).eq("id", session_id).execute()

        update_process_stage(sb, session_id, stage_name="synthesize", status="completed")
        return {"status": "completed", "session_id": session_id}

    except Exception as e:
        logger.exception("pipeline_failed", session_id=session_id)
        try:
            sb.table("intake_sessions").update({
                "process_status": "failed", "process_error": str(e)[:500],
            }).eq("id", session_id).execute()
        except Exception:
            pass
        return {"status": "failed", "session_id": session_id, "error": str(e)}

    finally:
        # Mandatory: close async clients inside the live loop
        await close_llm_client()
        await close_mcp_client()
        close_supabase_client()
