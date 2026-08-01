"""Dynamic prompt builder — assembles the system prompt every turn from session state.

Spec section 6: persona + role context + coverage table + next-move rules + tools.

The builder is intentionally a pure function: given the same session row, it
returns the same string. No I/O, no LLM calls.
"""

from __future__ import annotations

from typing import Any

from .persona import VOICE_PERSONA, TEXT_DELTA


_STATUS_GLYPH = {
    "validated": "[V]",
    "needs_probe": "[~]",
    "discussed": "[~]",
    "skipped": "[X]",
    "untouched": "[ ]",
}


def build_dynamic_prompt(session: dict[str, Any]) -> str:
    """Construct system prompt from current state. Called every turn.

    `session` is a dict matching the intake_sessions row shape (from
    intake_core.persistence.load_session). Required keys: form_data,
    questions_snapshot, current_answers, active_modality.
    """
    modality = session.get("active_modality") or "voice"
    sections = [
        _persona_section(modality),
        _role_context_section(session.get("form_data") or {}),
        _coverage_table_section(
            questions=session.get("questions_snapshot") or [],
            current_answers=session.get("current_answers") or {},
        ),
        _next_move_section(),
        _tools_section(),
    ]
    return "\n\n".join(sections)


def _persona_section(modality: str) -> str:
    if modality == "text":
        return VOICE_PERSONA + "\n\n" + TEXT_DELTA
    return VOICE_PERSONA


def _role_context_section(form_data: dict[str, Any]) -> str:
    role_name = form_data.get("role_name", "the role")
    exp_min = form_data.get("experience_min", "?")
    exp_max = form_data.get("experience_max")
    location = form_data.get("location", "—")
    jd_present = bool((form_data.get("jd_text") or "").strip())
    # A null/absent max means open-ended seniority ("X+ years"), not a literal
    # "None" in the prompt.
    experience = f"{exp_min}+ years" if exp_max is None else f"{exp_min}-{exp_max} years"
    lines = [
        "ROLE CONTEXT:",
        f"- Role: {role_name}",
        f"- Experience: {experience}",
        f"- Location: {location}",
        f"- JD on file: {'yes' if jd_present else 'no'}",
    ]
    return "\n".join(lines)


def _coverage_table_section(questions: list[dict], current_answers: dict[str, Any]) -> str:
    lines = ["CURRENT COVERAGE:"]
    for q in questions:
        qid = q["id"]
        topic = q["topic"]
        a = current_answers.get(qid) or {}
        status = a.get("status", "untouched")
        glyph = _STATUS_GLYPH.get(status, "[ ]")
        text = (a.get("text") or "").strip()
        conf = a.get("extraction_confidence", "none")
        snippet = ""
        if text:
            short = text if len(text) <= 80 else (text[:77] + "...")
            snippet = f' — "{short}" ({conf})'
        elif a.get("prefilled_text"):
            pre = a["prefilled_text"]
            short = pre if len(pre) <= 80 else (pre[:77] + "...")
            snippet = f' — prefill: "{short}" ({conf})'
        lines.append(f"{glyph} Q{q['order']} {topic}: {status}{snippet}")
    return "\n".join(lines)


def _next_move_section() -> str:
    return (
        "YOUR NEXT MOVE:\n"
        "- Prefer probing [~] (needs_probe / discussed) over starting [ ] (untouched).\n"
        "- For low-confidence prefills, lead with the prefill as an offer: "
        "\"your team has historically valued X — fair for this role?\"\n"
        "- NEVER re-ask a [V] (validated) question. Move on.\n"
        "- One thought at a time. Conversational. No markdown in voice.\n"
        "- When all 9 are [V] or [X], wrap with a warm goodbye and [END]."
    )


def _tools_section() -> str:
    return (
        "TOOLS AVAILABLE:\n"
        "- update_answer(qid, text, confidence, status?): record what the recruiter just said for one question. "
        "Call this after EVERY user turn that addresses a question.\n"
        "- mark_status(qid, status): mark a question as validated / needs_probe / discussed / skipped without changing the text.\n"
        "Tool calls do not appear in the conversation. Call them silently and naturally as you talk."
    )
