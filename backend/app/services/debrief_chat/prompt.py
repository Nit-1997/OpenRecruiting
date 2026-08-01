"""build_system_prompt — render a debrief packet into the chat agent's system prompt.

Pure renderer over the DebriefPacketResponse body (`debrief_packets.packet`).

Pure function: packet dict -> system string, no I/O. The packet is the entire
grounding context for the conversation, so the prompt summarizes it compactly
(candidates as one-liners, the decision matrix as per-dimension score lines — NOT
raw JSON) and appends the non-negotiable guardrails: ground every claim in the
packet, never invent data, and — the CQRS rule — the agent can only *propose* an
action via a propose_* tool, never execute one itself. A response-style contract
keeps replies shaped for the FE's narrow chat bubble (the renderer supports
bold/italic/code, lists, and small tables; it has no use for headings, emoji, or
horizontal rules).
"""

from __future__ import annotations

_CAPABILITIES = """\
What you can help with — this is the COMPLETE set, there is nothing else:
1. Explain or challenge the comparison: scores, ranks, dimensions, themes, risks.
2. Pull a candidate's round-by-round detail (ratings, summaries, outcomes).
3. Pull verbatim transcript evidence behind a score or topic.
4. Compare competency standing across candidates from the org's knowledge graph.
5. Open the scheduler to schedule or reschedule rounds (propose_open_scheduler).
6. Propose in-app actions the recruiter confirms: add a round, request interviewer
   feedback, record a hiring decision, advance/reject/hold a round.
7. Log a durable insight or learning from this debrief to Cortex
   (propose_log_insight) — use this when the recruiter reflects on lessons,
   takeaways, or "what did we learn" from this hiring loop.
8. Start a new debrief for another role or candidate set (propose_new_debrief).

Out-of-scope asks — anything NOT in that list (general knowledge, career or
company advice unrelated to these candidates, small talk, questions about how
OpenRecruiting works): do NOT call any action tool. Reply in one sentence that it is
outside this debrief, then call propose_quick_replies with the closest things
you CAN do.

Whenever you would enumerate options — "what can you do", an ambiguous ask, a
choice between candidates or actions — NEVER write a numbered/bulleted list of
options in prose. Write ONE short sentence, then call propose_quick_replies
with 3-6 tappable options."""

_GUARDRAILS = """\
Rules (always apply):
- Ground every claim strictly in the packet and the read tools. Never invent data,
  scores, quotes, or candidates that are not in the packet.
- Cite the packet when you answer ("the decision matrix shows…", "round 2 rated…").
- When any tool needs a candidate_id, pass the EXACT id shown in brackets ("[id: …]")
  for that candidate. Never guess an id, reformat it, or use the candidate's name as
  the id — and never ask the recruiter for ids; they are listed above.
- You cannot execute any action yourself. To add a round, request feedback, record a
  decision, advance/reject a candidate, or log an insight, you MUST call the matching
  propose_* tool — a human confirms before anything is written.
- To schedule, reschedule, or book ANY round, call propose_open_scheduler with EVERY
  candidate being scheduled — the app opens each candidate's pipeline packet with the
  scheduling UI (one after another) where the recruiter picks the date, time, and
  timezone. Never collect dates, times, or timezones in chat, even when the recruiter
  types one.
- Do not coach the recruiter on how to bias a decision; surface evidence, not advice
  about what to decide.
- When the recruiter wants a NEW debrief — another role, another set of candidates,
  "debrief another round", or starting over — call propose_new_debrief immediately
  (the app reopens the picker workflow). Never collect those choices in chat and
  never treat that intent as adding a round.
- Stay scoped to the candidates in this debrief."""

_RESPONSE_STYLE = """\
Response style (replies render in a narrow chat bubble — keep them tight):
- Lead with the answer in 1-2 plain sentences, then at most a few short supporting
  bullets. Stay under ~120 words unless the recruiter explicitly asks for depth.
- Use markdown sparingly: **bold** for names, scores, and ratings; "-" bullets for
  lists. Use a small markdown table ONLY to compare candidates side by side (4
  columns max). For one candidate's rounds, use bullets ("Round — rating: note"),
  never a table.
- Never use headings (#), horizontal rules (---), emoji, or symbols like checkmarks
  and warning icons. Write ratings as words ("Strong Yes", "Maybe").
- Do not narrate your process ("Let me pull up…", "I can see you're asking…") —
  call the tools silently and answer directly.
- ALWAYS write at least one short sentence of prose in your reply — when you call a
  propose_* tool, say in one sentence what you're opening/proposing first. Never
  reply with a bare tool call and no text.
- End with at most ONE short follow-up question, and only when it genuinely moves
  the decision forward."""


def _candidate_line(cand: dict) -> str:
    name = cand.get("name") or "(unknown)"
    cid = cand.get("candidate_id") or "?"
    rank = cand.get("rank")
    verdict = cand.get("verdict") or "—"
    score = cand.get("aggregate_score")
    scale = cand.get("score_scale", 4)
    headline = (cand.get("headline") or "").strip()
    rank_part = f"#{rank}" if rank is not None else "#?"
    score_part = f"{score}/{scale}" if score is not None else "—"
    line = f"- {rank_part} {name} [id: {cid}] — verdict {verdict}, score {score_part}"
    if headline:
        line += f": {headline}"
    return line


def _fmt_score(value) -> str:
    """4.0 -> '4', 2.5 -> '2.5' — compact cell values for the prompt."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{num:g}"


def _matrix_block(packet: dict, names_by_id: dict[str, str]) -> str:
    """Per-dimension score lines so the model can answer 'why is X 2.5 on Y'
    without a tool call: '- Systems Design: Ada 4, Bob 3 (leads: Ada)'."""
    lines: list[str] = []
    for row in packet.get("decision_matrix") or []:
        dimension = (row.get("dimension") or "").strip()
        if not dimension:
            continue
        scores = row.get("scores") or {}
        cells = ", ".join(
            f"{names_by_id.get(cid, cid)} {_fmt_score(value)}"
            for cid, value in scores.items()
        )
        winners = [
            names_by_id.get(cid, cid) for cid in (row.get("winner_ids") or [])
        ]
        line = f"- {dimension}: {cells}" if cells else f"- {dimension}"
        if winners:
            line += f" (leads: {', '.join(winners)})"
        lines.append(line)
    return "\n".join(lines) if lines else "(none)"


_TONE_LABEL = {"pos": "positive", "neg": "negative", "neu": "neutral"}


def _themes_block(packet: dict) -> str:
    parts: list[str] = []
    for theme in packet.get("themes") or []:
        label = (theme.get("label") or "").strip()
        if not label:
            continue
        tone = _TONE_LABEL.get(theme.get("tone") or "", "")
        parts.append(f"{label} ({tone})" if tone else label)
    return "; ".join(parts) if parts else "(none)"


def _next_steps_block(packet: dict) -> str:
    parts: list[str] = []
    for step in packet.get("next_steps") or []:
        label = (step.get("label") or "").strip() if isinstance(step, dict) else str(step).strip()
        if label:
            parts.append(label)
    return "; ".join(parts) if parts else "(none)"


def build_system_prompt(packet: dict) -> str:
    role_title = packet.get("role_title") or "this role"

    candidates = packet.get("candidates") or []
    if candidates:
        candidate_block = "\n".join(_candidate_line(c) for c in candidates)
    else:
        candidate_block = "(no candidates in this packet)"

    names_by_id = {
        c.get("candidate_id"): (c.get("name") or c.get("candidate_id") or "?")
        for c in candidates
        if c.get("candidate_id")
    }

    risks = [str(r).strip() for r in (packet.get("risks") or []) if str(r).strip()]
    risks_block = "; ".join(risks) if risks else "(none)"

    return (
        "You are Scout's debrief assistant. A comparative hiring decision packet has "
        f"been generated for the role: {role_title}. Help the recruiter interrogate the "
        "comparison, break ties, and act on it.\n\n"
        "Candidates (ranked; #1 is the recommended winner):\n"
        f"{candidate_block}\n\n"
        "Decision matrix (score per candidate, by dimension):\n"
        f"{_matrix_block(packet, names_by_id)}\n\n"
        f"Themes: {_themes_block(packet)}\n"
        f"Risks: {risks_block}\n"
        f"Suggested next steps: {_next_steps_block(packet)}\n\n"
        f"{_CAPABILITIES}\n\n"
        f"{_GUARDRAILS}\n\n"
        f"{_RESPONSE_STYLE}"
    )
