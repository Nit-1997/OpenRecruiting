"""Turn a screening interview transcript into a full scorecard by REUSING the
existing feedback Lambda pipeline.

The existing feedback Lambda is built around a HUMAN interviewer's assessment:
`candidate_rounds.scorecard_transcript` holds the assessor's verdict (the
"feedback"), and `transcripts.segments` holds the interview as corroborating
EVIDENCE. For the screening agent the AI both interviews AND assesses, so:

  1. The route persists the interview transcript to `transcripts.segments`
     (the EVIDENCE).
  2. This service has the AI AUTHOR an interviewer-style assessment from
     (screening plan + signals/must-haves + role + transcript) and writes it to
     `candidate_rounds.scorecard_transcript` (the "feedback").
  3. It triggers the existing feedback Lambda with `skip_prereq_check=True` — the
     UNCHANGED pipeline (extract -> evidence -> judge -> summary -> packet)
     produces a full (non-thin) scorecard.

`_author_assessment` is the single LLM seam for the prose scorecard (tests
monkeypatch it). `_compute_authenticity` is a SECOND, independent LLM seam that
returns STRUCTURED candidate-authenticity signals (specificity / consistency /
read-aloud likelihood + an overall directional confidence) persisted to
`candidate_rounds.authenticity_signals` and rendered as a dedicated recruiter
panel. It is deliberately decoupled from `_author_assessment` so it is separately
testable AND so a failure to compute it can never block the scorecard write or
the feedback Lambda trigger (it is a directional signal, not a gate).

All DB IO uses the custom async Supabase client (execute_async); the llm_core
gateway client is awaitable so no asyncio.to_thread wrapping is needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.dependencies import get_llm_client
from app.logging_config import get_logger

logger = get_logger(__name__)

_AUTHENTICITY_OVERALL = ("likely_authentic", "some_concern", "high_concern")
_AUTHENTICITY_LEVELS = ("low", "medium", "high")
_AUTHENTICITY_KINDS = ("specificity", "consistency", "read_aloud")

# Forced tool-use schema for the structured authenticity pass. Same pattern as
# screening_question_generator._TOOL — the model is forced to call this tool so
# we get clean JSON back without markdown-fence parsing.
_FORCE_AUTHENTICITY_TOOL = {
    "type": "function",
    "function": {"name": "emit_authenticity_signals"},
}

_AUTHENTICITY_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_authenticity_signals",
        "description": (
            "Emit a DIRECTIONAL read on how authentic / self-authored the candidate's "
            "screening answers appear. This is a soft signal to help the recruiter look "
            "closer — it is NOT proof and NOT a pass/fail gate."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "overall": {
                    "type": "string",
                    "enum": list(_AUTHENTICITY_OVERALL),
                    "description": "Overall directional read across all answers.",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "How confident you are in the overall read (0.0-1.0).",
                },
                "signals": {
                    "type": "array",
                    "description": "Specific patterns observed, one entry per pattern.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": list(_AUTHENTICITY_KINDS),
                                "description": (
                                    "specificity = how concrete/first-hand the detail is; "
                                    "consistency = internal coherence across answers; "
                                    "read_aloud = sounds scripted / AI-assisted / read aloud."
                                ),
                            },
                            "level": {
                                "type": "string",
                                "enum": list(_AUTHENTICITY_LEVELS),
                                "description": "Strength of this signal.",
                            },
                            "note": {
                                "type": "string",
                                "description": "One short sentence of evidence for this signal.",
                            },
                        },
                        "required": ["kind", "level", "note"],
                    },
                },
                "summary": {
                    "type": "string",
                    "description": "One-line directional note for the recruiter.",
                },
            },
            "required": ["overall", "confidence", "signals", "summary"],
        },
    },
}


def _bullets(items: list[str]) -> str:
    cleaned = [str(i).strip() for i in (items or []) if str(i).strip()]
    return "\n".join(f"- {i}" for i in cleaned) if cleaned else "- (none provided)"


def _normalize_authenticity(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce the LLM tool output into the stored contract: clamp confidence,
    drop malformed signal rows, and fall back to safe directional defaults so we
    never persist an off-contract shape. Returns {} if there is nothing usable,
    which the caller reads as "do not persist"."""
    if not isinstance(raw, dict) or not raw:
        # `not raw` is the truncated-tool-call shape: llm_core surfaces argument
        # JSON it could not parse as arguments={}. Without this, every branch
        # below falls through to its default and the function returns a complete,
        # truthy verdict of overall='likely_authentic' — which the caller then
        # PERSISTS to candidate_rounds.authenticity_signals and renders to a
        # hiring panel. A fabricated affirmative reading of a candidate is the
        # worst possible output of a degraded reply, and it was indistinguishable
        # from a real one. The schema marks all four top-level fields required, so
        # an empty payload is off-contract by definition; a partial one still gets
        # today's coercion, since that is a model wording the defaults exist for.
        return {}

    overall = raw.get("overall")
    if overall not in _AUTHENTICITY_OVERALL:
        overall = "likely_authentic"

    try:
        confidence = float(raw.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    signals: list[dict[str, str]] = []
    for item in raw.get("signals") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        level = item.get("level")
        note = str(item.get("note") or "").strip()
        if kind not in _AUTHENTICITY_KINDS or level not in _AUTHENTICITY_LEVELS:
            continue
        signals.append({"kind": kind, "level": level, "note": note})

    summary = str(raw.get("summary") or "").strip()

    return {
        "overall": overall,
        "confidence": confidence,
        "signals": signals,
        "summary": summary,
    }


def _segments_to_text(segments: list[dict] | None) -> str:
    """Render stored `{"speaker","text"}` segments back to a readable transcript."""
    if not isinstance(segments, list):
        return ""
    lines: list[str] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        speaker = str(seg.get("speaker") or "").strip()
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"{speaker}: {text}" if speaker else text)
    return "\n\n".join(lines)


class ScreeningFeedbackService:
    def __init__(self, db, feedback_job):
        self.db = db
        self.feedback_job = feedback_job

    async def generate_and_dispatch(self, candidate_round_id: str) -> None:
        ctx = await self._load(candidate_round_id)
        assessment = await self._author_assessment(ctx)
        if not assessment or not assessment.strip():
            logger.warning(
                "screening.feedback.assessment_empty",
                extra={
                    "event": "screening.feedback",
                    "status": "assessment_empty",
                    "candidate_round_id": candidate_round_id,
                },
            )
            return
        await self._write_scorecard_transcript(candidate_round_id, assessment)
        logger.info(
            "screening.feedback.assessment_authored",
            extra={
                "event": "screening.feedback",
                "status": "assessment_authored",
                "candidate_round_id": candidate_round_id,
                "assessment_chars": len(assessment),
            },
        )

        # Structured authenticity is a DIRECTIONAL signal, not a gate: compute it
        # independently of the prose assessment and never let a failure block the
        # scorecard write or the Lambda trigger below.
        try:
            signals = await self._compute_authenticity(ctx)
            if signals:
                await self._write_authenticity_signals(candidate_round_id, signals)
                logger.info(
                    "screening.feedback.authenticity_computed",
                    extra={
                        "event": "screening.feedback",
                        "status": "authenticity_computed",
                        "candidate_round_id": candidate_round_id,
                        "overall": signals.get("overall"),
                    },
                )
        except Exception as exc:  # noqa: BLE001 — best-effort directional signal.
            logger.warning(
                "screening.feedback.authenticity_failed",
                extra={
                    "event": "screening.feedback",
                    "status": "authenticity_failed",
                    "candidate_round_id": candidate_round_id,
                    "error": str(exc)[:200],
                },
            )

        await self.feedback_job.trigger_feedback_processing(
            candidate_round_id, skip_prereq_check=True
        )
        logger.info(
            "screening.feedback.lambda_triggered",
            extra={
                "event": "screening.feedback",
                "status": "lambda_triggered",
                "candidate_round_id": candidate_round_id,
                "assessment_chars": len(assessment),
            },
        )

    async def _load(self, candidate_round_id: str) -> dict[str, Any]:
        """Gather everything the assessor prompt needs: the screening config +
        questions (signals/must-haves), the role context, and the interview
        transcript text (read back from transcripts.segments).
        """
        cr_result = await (
            self.db.table("candidate_rounds")
            .select("id, round_id, candidate_id")
            .eq("id", candidate_round_id)
            .single()
            .execute_async()
        )
        cr = cr_result.data or {}
        round_id = cr.get("round_id")
        candidate_id = cr.get("candidate_id")

        config = await self._load_screening_config(round_id) if round_id else {}
        role = await self._load_role_context(candidate_id) if candidate_id else {}
        transcript_text = await self._load_transcript_text(candidate_round_id)

        return {
            "candidate_round_id": candidate_round_id,
            "questions": config.get("questions", []),
            "role": role,
            "transcript_text": transcript_text,
        }

    async def _load_screening_config(self, round_id: str) -> dict[str, Any]:
        cfg_result = await (
            self.db.table("round_screening_configs")
            .select("id")
            .eq("round_id", round_id)
            .single()
            .execute_async()
        )
        config = cfg_result.data
        if not config:
            return {"questions": []}

        q_result = await (
            self.db.table("round_screening_questions")
            .select("title, prompt, probe, signal, dimension, order_index")
            .eq("round_screening_config_id", config["id"])
            .order("order_index")
            .execute_async()
        )
        return {"questions": q_result.data or []}

    async def _load_role_context(self, candidate_id: str) -> dict[str, Any]:
        cand_result = await (
            self.db.table("candidates")
            .select("requisition_id")
            .eq("id", candidate_id)
            .single()
            .execute_async()
        )
        requisition_id = (cand_result.data or {}).get("requisition_id")
        if not requisition_id:
            return {}

        req_result = await (
            self.db.table("requisitions")
            .select(
                "role_title, role_location, must_have_skills, good_to_have_skills, "
                "intake_notes"
            )
            .eq("id", requisition_id)
            .single()
            .execute_async()
        )
        req = req_result.data or {}
        return {
            "role_title": req.get("role_title") or "Unknown",
            "role_location": req.get("role_location") or "",
            "must_have_skills": req.get("must_have_skills") or [],
            "good_to_have_skills": req.get("good_to_have_skills") or [],
            "intake_notes": req.get("intake_notes") or "",
        }

    async def _load_transcript_text(self, candidate_round_id: str) -> str:
        result = await (
            self.db.table("transcripts")
            .select("segments")
            .eq("candidate_round_id", candidate_round_id)
            .single()
            .execute_async()
        )
        segments = (result.data or {}).get("segments")
        return _segments_to_text(segments)

    def _build_prompt(self, ctx: dict[str, Any]) -> str:
        role = ctx.get("role") or {}
        questions = ctx.get("questions") or []
        transcript = ctx.get("transcript_text") or "(no transcript captured)"

        q_lines: list[str] = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            title = (q.get("title") or "").strip()
            prompt = (q.get("prompt") or "").strip()
            signal = (q.get("signal") or "").strip()
            dimension = (q.get("dimension") or "").strip()
            parts = [f"- {title or prompt}"]
            if prompt and title:
                parts.append(f"  Asked: {prompt}")
            if signal:
                parts.append(f"  Signal: {signal}")
            if dimension:
                parts.append(f"  Dimension: {dimension}")
            q_lines.append("\n".join(parts))
        questions_block = "\n".join(q_lines) if q_lines else "- (no screening questions configured)"

        return f"""You are writing the interviewer's assessment of a candidate after a screening interview.

Given the role, the screening questions and their signals/must-haves, and the
interview transcript, write a concise interviewer-style assessment covering each
signal with specific evidence from the candidate's answers, then a short
AUTHENTICITY NOTE flagging anything that suggests read-aloud / AI-assisted /
low-specificity answers (latency, vagueness, inconsistency).

<role>
Role: {role.get("role_title") or "Unknown"}
Location: {role.get("role_location") or "(unspecified)"}
Must-have skills:
{_bullets(role.get("must_have_skills") or [])}
Good-to-have skills:
{_bullets(role.get("good_to_have_skills") or [])}
Notes: {role.get("intake_notes") or "(none)"}
</role>

<screening_questions>
{questions_block}
</screening_questions>

<interview_transcript>
{transcript}
</interview_transcript>

Write the assessment as plain prose an interviewer would submit. Cover each
signal/competency with concrete evidence quoted or paraphrased from the
candidate's answers. End with a section titled "AUTHENTICITY NOTE" that flags any
signs of read-aloud / AI-assisted / generic answers, or states the answers
appeared genuine if nothing stands out. Output plain text only — no markdown
headers, no preamble."""

    async def _author_assessment(self, ctx: dict[str, Any]) -> str:
        """Single LLM seam. Authors the interviewer-style assessment + authenticity
        appendix as plain text (this becomes scorecard_transcript)."""
        llm = get_llm_client()
        model = get_settings().SCREENING_ASSESSOR_MODEL
        prompt = self._build_prompt(ctx)
        reply = await llm.complete(
            model=model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        # The one site in this phase that reads prose rather than a tool call, so
        # it passes no tools and no tool_choice. LLMReply.text is already the
        # joined text of every text block, which is what the loop here did.
        return (reply.text or "").strip()

    def _build_authenticity_prompt(self, ctx: dict[str, Any]) -> str:
        role = ctx.get("role") or {}
        transcript = ctx.get("transcript_text") or "(no transcript captured)"
        return f"""You are reviewing a screening interview transcript for DIRECTIONAL
authenticity signals — patterns that suggest a candidate's answers may have been
read aloud, AI-assisted, or low on first-hand specificity. This is a soft signal
to help the recruiter look closer; it is NOT proof and NOT a pass/fail gate.

Judge ONLY what is feasible from the transcript text:
- specificity: are answers concrete and first-hand (names, numbers, trade-offs,
  what THEY did), or generic/textbook?
- consistency: do the answers cohere with each other, or contradict / drift?
- read_aloud: does the phrasing sound scripted, essay-like, or AI-assisted
  (overly polished, uniform register, list-like recitation) vs. natural speech?

Do NOT speculate about response latency or timing — that data is not available
here. Stay measured: prefer "likely_authentic" / "low" unless the text clearly
supports concern. Be fair to non-native speakers and nervous candidates: formal
phrasing alone is not a red flag.

<role>
Role: {role.get("role_title") or "Unknown"}
</role>

<interview_transcript>
{transcript}
</interview_transcript>

Respond ONLY by calling emit_authenticity_signals."""

    async def _compute_authenticity(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Second LLM seam (independent of _author_assessment). Forces the
        emit_authenticity_signals tool call and returns a NORMALIZED structured
        dict of DIRECTIONAL authenticity signals. Tests monkeypatch this.

        Latency analysis is intentionally out of scope: the persisted transcript
        segments carry no reliable per-turn timestamps yet (the voice agent sends
        a formatted string), so we compute only text-derivable signals. Latency is
        a future enhancement once timestamped turns are available.
        """
        llm = get_llm_client()
        model = get_settings().SCREENING_ASSESSOR_MODEL
        prompt = self._build_authenticity_prompt(ctx)
        reply = await llm.complete(
            model=model,
            max_tokens=1200,
            tools=[_AUTHENTICITY_TOOL],
            tool_choice=_FORCE_AUTHENTICITY_TOOL,
            messages=[{"role": "user", "content": prompt}],
        )
        call = reply.tool_call_named("emit_authenticity_signals")
        if call is None:
            # Defence in depth behind the forced tool. {} is the caller's "no
            # signals" contract, so this branch is otherwise indistinguishable
            # from a transcript that produced nothing worth flagging — and this
            # output reaches a hiring panel, so the difference matters.
            logger.warning(
                "screening.feedback.authenticity_no_tool_call",
                extra={
                    "event": "screening.feedback",
                    "status": "authenticity_no_tool_call",
                    "alias": model,
                    "finish_reason": reply.finish_reason,
                },
            )
            return {}
        return _normalize_authenticity(call.arguments or {})

    async def _write_scorecard_transcript(
        self, candidate_round_id: str, text: str
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await (
            self.db.table("candidate_rounds")
            .update({"scorecard_transcript": text, "updated_at": now})
            .eq("id", candidate_round_id)
            .execute_async()
        )

    async def _write_authenticity_signals(
        self, candidate_round_id: str, signals: dict[str, Any]
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await (
            self.db.table("candidate_rounds")
            .update({"authenticity_signals": signals, "updated_at": now})
            .eq("id", candidate_round_id)
            .execute_async()
        )


def get_screening_feedback_service() -> ScreeningFeedbackService:
    from app.services.feedback_job_service import get_feedback_job_service
    from app.services.supabase import get_supabase_admin_client

    return ScreeningFeedbackService(
        db=get_supabase_admin_client(),
        feedback_job=get_feedback_job_service(),
    )
