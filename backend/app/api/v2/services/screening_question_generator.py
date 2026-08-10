"""Generate rich screening questions for a round.

Mirrors the intake Lambda's question style (workers/intake-agent/
src/prompts/scorecard.py): each question carries title / prompt / probe / signal
/ dimension / duration_minutes. The recruiter edits the result before saving.

`_call_llm` is the single seam that touches the LLM gateway, so tests can
monkeypatch it. It uses the tool-use forced-call pattern (same as the JD parser)
to get structured JSON back without markdown-fence parsing.

The persona text is reused from intake-core rather than re-stated here, so the
generator and the runtime voice agent stay anchored to the same persona.
"""

from __future__ import annotations

from typing import Any

import structlog
from intake_core.screening.persona import GENERIC_SCREENING_PERSONA

from app.api.v2.schemas.screening import ScreeningQuestion
from app.config import get_settings
from app.dependencies import get_llm_client

logger = structlog.get_logger(__name__)

_FORCE_TOOL = {"type": "function", "function": {"name": "emit_screening_questions"}}

_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_screening_questions",
        "description": (
            "Emit 3-5 voice-screening questions for the role. Each question is a single "
            "conversational opener the interviewer reads aloud, plus a follow-up probe and "
            "the signal/dimension it targets."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Short label for the question (2-5 words).",
                            },
                            "prompt": {
                                "type": "string",
                                "description": "The open question the interviewer asks aloud.",
                            },
                            "probe": {
                                "type": "string",
                                "description": "One follow-up to dig a layer deeper if the answer is thin.",
                            },
                            "signal": {
                                "type": "string",
                                "description": "What this question evaluates (e.g. EXECUTION, DEPTH, OWNERSHIP).",
                            },
                            "dimension": {
                                "type": "string",
                                "description": "The competency/area the question maps to.",
                            },
                            "duration_minutes": {
                                "type": "integer",
                                "description": "Rough minutes to spend on this question (3-8).",
                            },
                        },
                        "required": ["title", "prompt"],
                    },
                }
            },
            "required": ["questions"],
        },
    },
}


def _bullets(items: list[str]) -> str:
    cleaned = [str(i).strip() for i in (items or []) if str(i).strip()]
    return "\n".join(f"- {i}" for i in cleaned) if cleaned else "- (none provided)"


class ScreeningQuestionGenerator:
    """Builds the prompt + maps the LLM output to ScreeningQuestion models."""

    def _build_prompt(
        self,
        *,
        role_context: str,
        must_haves: list[str],
        cortex_gaps: list[str],
        preferences: str | None,
    ) -> str:
        pref_block = (
            f"\n<recruiter_preferences>\n{preferences.strip()}\n</recruiter_preferences>\n"
            if preferences and preferences.strip()
            else ""
        )
        return f"""{GENERIC_SCREENING_PERSONA}

You are designing the questions for a voice-based screening round. Produce 3-5
questions that surface real signal in a short conversational screen — not a
written exam. Each question must be a single open prompt the interviewer reads
aloud, with one follow-up probe, and the signal + competency dimension it targets.

<role_context>
{role_context.strip() or "(no role context provided)"}
</role_context>

<must_haves>
{_bullets(must_haves)}
</must_haves>

<gaps_to_close>
These are areas where the current evidence on the role is thin — prioritise
questions that close these gaps.
{_bullets(cortex_gaps)}
</gaps_to_close>
{pref_block}
Design principles:
- Each question targets a distinct signal — minimise overlap.
- Prefer behavioural / "tell me about a time" prompts that draw out concrete stories.
- Keep prompts conversational and answerable by voice in a few minutes.
- The probe should dig one layer deeper (root cause, trade-off, what they'd change).
- Never ask about protected characteristics or anything biased/illegal.

Respond ONLY by calling emit_screening_questions."""

    async def _call_llm(self, prompt: str) -> dict[str, Any]:
        """Single LLM seam. Forces the emit_screening_questions tool call and
        returns its parsed input dict (`{"questions": [...]}`)."""
        llm = get_llm_client()
        model = get_settings().SCREENING_GENERATOR_MODEL
        reply = await llm.complete(
            model=model,
            max_tokens=2000,
            tools=[_TOOL],
            tool_choice=_FORCE_TOOL,
            messages=[{"role": "user", "content": prompt}],
        )
        call = reply.tool_call_named("emit_screening_questions")
        if call is None:
            # Defence in depth behind the forced tool: a prose reply, or one
            # naming another tool. generate() reads {"questions": []} as "the
            # model produced nothing" and falls back, which is also what a
            # truncated call arrives as — so the two are separated in the log.
            logger.warning(
                "screening_questions_no_tool_call",
                alias=model,
                finish_reason=reply.finish_reason,
            )
            return {"questions": []}
        return call.arguments or {"questions": []}

    async def generate(
        self,
        *,
        role_context: str,
        must_haves: list[str],
        cortex_gaps: list[str],
        preferences: str | None,
    ) -> list[ScreeningQuestion]:
        prompt = self._build_prompt(
            role_context=role_context,
            must_haves=must_haves,
            cortex_gaps=cortex_gaps,
            preferences=preferences,
        )
        try:
            parsed = await self._call_llm(prompt)
        except Exception as exc:  # noqa: BLE001 — generation is best-effort; the
            # recruiter can still author questions by hand on an empty result.
            logger.warning("screening_generate_llm_failed", error=str(exc))
            return []

        questions: list[ScreeningQuestion] = []
        for idx, raw in enumerate(parsed.get("questions") or []):
            if not isinstance(raw, dict):
                continue
            title = (raw.get("title") or "").strip()
            prompt_text = (raw.get("prompt") or "").strip()
            if not title or not prompt_text:
                continue
            questions.append(
                ScreeningQuestion(
                    order_index=idx,
                    title=title,
                    prompt=prompt_text,
                    probe=(raw.get("probe") or "").strip() or None,
                    signal=(raw.get("signal") or "").strip() or None,
                    dimension=(raw.get("dimension") or "").strip() or None,
                    duration_minutes=raw.get("duration_minutes") or 5,
                )
            )
        return questions
