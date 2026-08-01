"""Normalize raw step files (from manual SQL extraction) into one Fixture JSON.

Inputs (under input-dir):
  step2_round.json    — candidate_rounds + candidates + requisitions
  step3_questions.json — feedback_questions (topics)
  step4_transcript.json — transcripts (feedback_transcript + segments)
  step5_bot.json      — recall_bots (for feedback_start_timestamp)

Output: a single fixture JSON conforming to scripts._fixture_schema.Fixture.

PII redaction is name-only:
  - Candidate name → "Candidate" (in scorecard, feedback_transcript, job_description,
    and every segments[].words[].text)
  - Any other human participant → "Interviewer", "Interviewer 2", ...
  - participant dict rebuilt from a whitelist: only {id, name} survive
  - raw_transcript_url stripped (signed S3 URL leaks)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

from dateutil import parser as dt_parser

from scripts._fixture_schema import (
    BaselineOutputs,
    FeedbackSource,
    Fixture,
    Question,
    RedactionInfo,
    RoleContext,
    Transcript,
)

BOT_VENDOR_NAMES = {"openrecruiting", "openrecruiting ai", "openrecruiting interview assistant"}


def _load_single_row(path: Path) -> dict:
    with path.open() as f:
        rows = json.load(f)
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path.name}: expected non-empty JSON array, got {type(rows).__name__}")
    return rows[0]


def _load_rows(path: Path) -> list[dict]:
    with path.open() as f:
        rows = json.load(f)
    if not isinstance(rows, list):
        raise ValueError(f"{path.name}: expected JSON array, got {type(rows).__name__}")
    return rows


def _compute_feedback_start_timestamp(bot_row: dict) -> float | None:
    started = bot_row.get("feedback_started_at")
    joined = bot_row.get("joined_at")
    if not started or not joined:
        return None
    try:
        return (dt_parser.isoparse(started) - dt_parser.isoparse(joined)).total_seconds()
    except (ValueError, TypeError):
        return None


def _resolve_source(round_row: dict, bot_row: dict) -> tuple[str, str | None]:
    """Returns (source, scorecard_transcript) per get_feedback_source priority."""
    scorecard = round_row.get("scorecard_transcript")
    if scorecard and scorecard.strip():
        return "scorecard", scorecard

    status = (bot_row or {}).get("feedback_status")
    if status in ("completed", "partial", "collecting", "voice_active"):
        return "bot", None

    return "none", None


def _candidate_name_variants(candidate_name: str) -> list[str]:
    """Generate name forms to redact: full name + non-trivial tokens (e.g. first name).

    Returns variants sorted longest-first so the regex matches "Lena Ortiz" before "Lena".
    Tokens of length <= 1 are skipped to avoid clobbering single-letter words.
    """
    variants = {candidate_name}
    for token in candidate_name.split():
        if len(token) > 1:
            variants.add(token)
    return sorted(variants, key=len, reverse=True)


def _redact_segments(segments: list[dict], candidate_name: str) -> tuple[list[dict], dict[str, str]]:
    """Returns (redacted_segments, interviewer_name_map).

    interviewer_name_map maps original interviewer names → redacted labels for trace.

    Participant dicts are rebuilt from a whitelist: only `id` and (redacted) `name`
    survive. This is defensive — future Recall schema fields can't leak PII through.

    Each word's `text` field is also redacted with the same candidate-name policy so
    per-word transcribed data stays consistent with the derived feedback_transcript.
    """
    candidate_aliases = {v.lower() for v in _candidate_name_variants(candidate_name)}
    interviewer_count = 0
    name_map: dict[str, str] = {}
    out: list[dict] = []
    for seg in segments:
        raw_participant = seg.get("participant") or {}
        orig_name = (raw_participant.get("name") or "").strip()
        lowered = orig_name.lower()
        if not orig_name:
            new_name = "Unknown"
        elif lowered in candidate_aliases:
            new_name = "Candidate"
        elif lowered in BOT_VENDOR_NAMES:
            new_name = orig_name  # keep bot vendor name
        else:
            if orig_name not in name_map:
                interviewer_count += 1
                suffix = "" if interviewer_count == 1 else f" {interviewer_count}"
                name_map[orig_name] = f"Interviewer{suffix}"
            new_name = name_map[orig_name]

        # Whitelist participant fields. id (if present) + redacted name only.
        new_participant: dict = {"name": new_name}
        if "id" in raw_participant:
            new_participant["id"] = raw_participant["id"]

        new_seg = dict(seg)
        new_seg["participant"] = new_participant

        # Redact each word's transcribed text. Words structure preserved.
        raw_words = seg.get("words") or []
        new_words: list = []
        for w in raw_words:
            if isinstance(w, dict) and "text" in w:
                new_w = dict(w)
                new_w["text"] = _redact_text(w.get("text"), candidate_name)
                new_words.append(new_w)
            else:
                new_words.append(w)
        new_seg["words"] = new_words

        out.append(new_seg)
    return out, name_map


def _redact_text(text: str | None, candidate_name: str) -> str:
    if not text:
        return text or ""
    # Match full name and individual tokens (e.g., "Lena Ortiz" and "Lena").
    # Longest-first ordering ensures full name matches before first name.
    variants = _candidate_name_variants(candidate_name)
    pattern = re.compile("|".join(re.escape(v) for v in variants), re.IGNORECASE)
    return pattern.sub("Candidate", text)


def _seniority(round_row: dict) -> str:
    lo = round_row.get("experience_min_years") or 0
    hi = round_row.get("experience_max_years")
    return f"{lo}-{hi} Years" if hi else f"{lo}+ Years"


def normalize(input_dir: Path) -> Fixture:
    round_row = _load_single_row(input_dir / "step2_round.json")
    questions_rows = _load_rows(input_dir / "step3_questions.json")
    transcript_row = _load_single_row(input_dir / "step4_transcript.json")
    bot_rows = _load_rows(input_dir / "step5_bot.json")
    bot_row = bot_rows[0] if bot_rows else {}

    candidate_name = (round_row.get("candidate_name") or "").strip() or "Candidate"
    source, scorecard_text = _resolve_source(round_row, bot_row)

    raw_segments = transcript_row.get("segments") or []
    segments, interviewer_map = _redact_segments(raw_segments, candidate_name)

    feedback_transcript_raw = transcript_row.get("feedback_transcript") or ""

    fixture = Fixture(
        fixture_version=1,
        round_id=round_row["candidate_round_id"],
        captured_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        source_environment="production",
        redaction=RedactionInfo(
            candidate_name=candidate_name,
            interviewer_names=interviewer_map,
        ),
        feedback_source=FeedbackSource(
            source=source,
            scorecard_transcript=_redact_text(scorecard_text, candidate_name) if scorecard_text else None,
            has_interview_transcript=bool(raw_segments),
        ),
        questions=[
            Question(
                id=q["id"],
                question_number=q["question_number"],
                heading=q["heading"],
                description=q["description"],
            )
            for q in questions_rows
        ],
        role_context=RoleContext(
            role=round_row.get("role_title") or "Unknown",
            seniority=_seniority(round_row),
            location=round_row.get("role_location") or "Unknown",
            must_have_skills=round_row.get("must_have_skills") or [],
            good_to_have_skills=round_row.get("good_to_have_skills") or [],
            intake_notes=round_row.get("intake_notes") or "",
            job_description=_redact_text(round_row.get("job_description") or "", candidate_name),
        ),
        transcript=Transcript(
            feedback_transcript=_redact_text(feedback_transcript_raw, candidate_name),
            segments=segments,
            feedback_start_timestamp=_compute_feedback_start_timestamp(bot_row),
        ),
        baseline_outputs=BaselineOutputs(
            rating=round_row.get("current_rating"),
            summary=round_row.get("current_summary"),
            question_summaries=round_row.get("current_question_summaries") or {},
            competency_snapshots=round_row.get("current_competency_snapshots"),
        ),
    )
    return fixture


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    fixture = normalize(args.input_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(fixture.model_dump_json(indent=2))
    print(f"wrote {args.output} ({args.output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
