"""End-to-end smoke test for Phase 2: v2 voice agent reads session, builds prompt,
binds tools, persists turns, runs coverage tracker.

This does NOT exercise WebRTC media — that's deferred to live recruiter testing.
It DOES exercise: session load, dynamic prompt build, tool dispatch, turn persist,
coverage tracker call.

Usage:
    export SUPABASE_URL=...
    export SUPABASE_SECRET_KEY=...
    export ANTHROPIC_API_KEY=...
    export TEST_SESSION_ID=<a ready session id from Phase 1>
    python3 scripts/smoke_test_v2.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, ".")
sys.path.insert(0, "../intake-core")


async def main() -> int:
    from supabase import create_client

    from src.session_loader import load_intake_session_for_voice, format_turns_for_llm
    from src.persona.dynamic_intake import build_voice_intake_prompt
    from src.pipeline.tool_dispatch import dispatch_tool_call
    from intake_core.coverage_tracker import run_coverage_tracker
    from intake_core.tools import INTAKE_TOOLS

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    session_id = os.environ["TEST_SESSION_ID"]

    print(f"[1] Loading session {session_id}...")
    row = load_intake_session_for_voice(sb, session_id)
    print(f"    status={row['status']} active_modality={row.get('active_modality')}")
    print(f"    {len(row.get('turns', []))} prior turns, {len((row.get('current_answers') or {}))} answer keys")

    print("[2] Building dynamic prompt...")
    prompt = build_voice_intake_prompt(row)
    assert "You are Scout" in prompt
    assert "CURRENT COVERAGE" in prompt
    assert "update_answer" in prompt
    print(f"    {len(prompt)} chars; sample: '{prompt[:80]}...'")

    print("[3] Formatting prior turns for LLM context...")
    msgs = format_turns_for_llm(row.get("turns", []))
    print(f"    {len(msgs)} messages")

    print("[4] Validating tool schemas...")
    # Through the same reader the pipeline uses, so this script cannot drift from
    # the shape factory.build_pipeline actually consumes.
    from src.pipeline.tool_schemas import tool_name

    assert {tool_name(t) for t in INTAKE_TOOLS} == {'update_answer', 'mark_status'}
    print(f"    {len(INTAKE_TOOLS)} tools: {[tool_name(t) for t in INTAKE_TOOLS]}")

    print("[5] Dispatching a synthetic update_answer tool call...")
    out = dispatch_tool_call(
        client=sb,
        session_id=session_id,
        tool_name="update_answer",
        tool_args={
            "qid": "q1_role_overview",
            "text": f"smoke-test value {uuid.uuid4()}",
            "confidence": "medium",
            "status": "discussed",
        },
        turn_idx=999,
    )
    assert out["ok"] is True
    print(f"    ok: {out}")

    print("[6] Running coverage tracker (live gateway call)...")
    from llm_core import get_client as get_llm_client

    # No try/finally: the gateway client is a process singleton, not a per-call
    # resource, so closing it here would tear down the shared transport.
    llm = get_llm_client()
    result = await run_coverage_tracker(
        supabase_client=sb,
        llm=llm,
        model="voice-intake",
        session_id=session_id,
        last_user_turn="Skip the team-structure question for now.",
        debounce_ms=0,
    )
    print(f"    tracker result: ok={result['ok']} applied={result.get('applied')} patch_keys={list((result.get('patch') or {}).keys())}")

    print("[7] Re-loading session to confirm tool + tracker writes landed...")
    row2 = load_intake_session_for_voice(sb, session_id)
    q1 = (row2.get("current_answers") or {}).get("q1_role_overview", {})
    print(f"    q1_role_overview.status={q1.get('status')} text_excerpt={(q1.get('text') or '')[:60]}")
    assert q1.get("status") in {"discussed", "validated"}

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
